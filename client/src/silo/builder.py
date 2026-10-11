import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import xxhash
from filelock import FileLock, Timeout

from silo.build_context import BuildContext
from silo.build_id import compiler_fingerprint, make_build_id, recipe_hash
from silo.build_profile import Profile
from silo.cache import remove_tree
from silo.dependency import OptionValue
from silo.dependency_graph import Graph, Node, resolve, validate
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.git_snapshot import checkout_tree
from silo.package import Package, artifact_dirs, stored_components, write_package
from silo.paths import builds_dir, store_dir
from silo.platform import backend_for
from silo.platform.base import PlatformBackend
from silo.report import BuildReport
from silo.silo_package import SiloPackage
from silo.source import SourceTree, fetch_source
from silo.tool_resolver import is_fetched_tool, resolve_tool

# Where `silo sync` writes inside a project
PROJECT_DIR = ".silo"


@dataclass(frozen=True)
class NodeInputs:
    """The store paths one package's build draws on."""

    # Every package it links, directly or not
    dependencies: dict[str, Path] = field(default_factory=dict)
    # The recipes it declared with self.tool()
    tools: dict[str, Path] = field(default_factory=dict)
    # Those tools together with what they link, which they need in order to start
    tool_runtime: tuple[Path, ...] = ()


@dataclass(frozen=True)
class BuiltGraph:
    store_paths: dict[str, Path]
    build_ids: dict[str, str]


@dataclass(frozen=True)
class BuiltTools:
    packages: dict[str, Path] = field(default_factory=dict)
    runtime: tuple[Path, ...] = ()
    build_ids: tuple[str, ...] = ()


def build_environment(
    package: SiloPackage, profile: Profile, inputs: NodeInputs, tmp: Path
) -> dict[str, str]:
    """The environment for building `package`: its compiler, its tools and what they need to run.

    Shared libraries of its dependencies are findable too, so tests and tools start.
    """
    backend = backend_for(profile.settings.os)
    fetched = [resolve_tool(tool) for tool in package._declared_tools if is_fetched_tool(tool)]
    tool_dirs = [tool.bin_dir for tool in fetched]
    for tool_package in inputs.tools.values():
        tool_dirs += artifact_dirs(tool_package, "executable")
    env = backend.build_env(profile, tool_dirs, tmp)

    library_dirs: list[Path] = []
    for package_dir in [*inputs.dependencies.values(), *inputs.tool_runtime]:
        library_dirs += artifact_dirs(package_dir, "shared_lib")
    if library_dirs:
        variable = backend.runtime_library_variable
        searched = [*dict.fromkeys(map(str, library_dirs)), env.get(variable, "")]
        env[variable] = os.pathsep.join(path for path in searched if path)
    return env


@dataclass(frozen=True)
class WorkDirs:
    root: Path

    @property
    def lock_file(self) -> Path:
        return self.root.with_name(self.root.name + ".lock")

    @property
    def source(self) -> Path:
        return self.root / "src"

    @property
    def source_index(self) -> Path:
        return self.root / "source.index"

    @property
    def source_state(self) -> Path:
        return self.root / "source-state.json"

    @property
    def build(self) -> Path:
        return self.root / "build"

    @property
    def stage(self) -> Path:
        return self.root / "stage"

    @property
    def generated(self) -> Path:
        return self.root / "generated"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    def reset_scratch(self) -> None:
        """Source and build survive between runs, so rebuilds are incremental."""
        for scratch in (self.stage, self.generated, self.tmp):
            if scratch.exists():
                shutil.rmtree(scratch)
        self.tmp.mkdir(parents=True)


@contextlib.contextmanager
def work_lock(dirs: WorkDirs, label: str) -> Generator[None]:
    """Hold a work dir for one process. Another silo building the same thing waits here."""
    dirs.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(dirs.lock_file)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print(f"{label}: waiting for another silo process that is building it")
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def work_key(node: Node, build_id: str, profile: Profile) -> str:
    """Names a package's work dir and its sentinel install prefix.

    Fetched source uses the build id. Local source changes its build id on every edit, so it
    uses a key that stays the same for one folder and configuration, keeping its build dir.
    """
    if not node.source.local_source:
        return build_id
    stable_inputs = [
        str(node.source.local_dir),
        node.build_type.value,
        compiler_fingerprint(profile),
        node.package.options.model_dump_json(),
    ]
    return "local-" + xxhash.xxh128("|".join(stable_inputs).encode()).hexdigest()[:16]


def prepare_source(node: Node, dirs: WorkDirs) -> None:
    """Put the source in the work dir and run the recipe's patch() on it, if anything changed."""
    package, source = node.package, node.source
    tree = SourceTree(dirs.source, package.recipe_dir)

    if not source.local_source:
        if not dirs.source.exists():
            fetch_source(source, dirs.source)
            package.patch(tree)
        return

    assert source.local_dir is not None and source.tree is not None
    wanted = {"tree": source.tree, "recipe": recipe_hash(package.recipe_dir, True)}
    if dirs.source_state.exists() and json.loads(dirs.source_state.read_text()) == wanted:
        return
    checkout_tree(source.local_dir, source.tree, dirs.source, dirs.source_index)
    package.patch(tree)
    dirs.source_state.write_text(json.dumps(wanted))


def inferred_package(node: Node, backend: PlatformBackend) -> Package:
    package = Package.infer(node.package.install_dir, node.name, backend)
    has_library = any(component.static_libs for component in package.components)
    if has_library and node.dependency_names:
        # An inferred library would silently drop what its consumers must also link
        raise SiloError(
            f"{node.name} builds a library and depends on {', '.join(node.dependency_names)}. "
            "Add a package() hook whose components say what they require."
        )
    return package


def build_node(
    node: Node,
    build_id: str,
    profile: Profile,
    inputs: NodeInputs,
    report: BuildReport | None = None,
) -> Path:
    """Build one package into the store and return its store path. A store hit builds nothing."""
    label = f"{node.name}-{node.version}-{build_id}"
    store_path = store_dir() / label
    if store_path.exists():
        print(f"{label}: already in the store")
        if report:
            report.record(node, build_id, "cached", store_path)
        return store_path

    key = work_key(node, build_id, profile)
    dirs = WorkDirs(builds_dir() / f"{node.name}-{key}")
    with work_lock(dirs, label):
        if store_path.exists():
            print(f"{label}: built by another silo process")
            if report:
                report.record(node, build_id, "cached", store_path)
            return store_path
        log = report.log_for(label) if report else None
        try:
            _build_into_store(node, build_id, profile, inputs, dirs, key, store_path, log)
        except Exception as error:
            if report:
                report.record(node, build_id, "failed", error=error)
            raise
        if not node.source.local_source:
            # Kept on failure for inspection, and for local source so rebuilds are incremental
            remove_tree(dirs.root)
    print(f"{label}: stored at {store_path}")
    if report:
        report.record(node, build_id, "built", store_path)
    return store_path


def _build_into_store(
    node: Node,
    build_id: str,
    profile: Profile,
    inputs: NodeInputs,
    dirs: WorkDirs,
    key: str,
    store_path: Path,
    log: Path | None = None,
) -> None:
    package = node.package
    label = store_path.name
    backend = backend_for(profile.settings.os)
    dirs.reset_scratch()

    package._context = BuildContext(
        profile=profile,
        build_type=node.build_type,
        env=build_environment(package, profile, inputs, dirs.tmp),
        source_dir=dirs.source,
        build_dir=dirs.build,
        stage_dir=dirs.stage,
        generated_dir=dirs.generated,
        install_prefix=f"/silo-prefix-{key}",
        local_source=node.source.local_source,
        dependency_packages=inputs.dependencies,
        tool_packages=inputs.tools,
        log=log,
    )

    print(f"{label}: preparing source")
    prepare_source(node, dirs)

    print(f"{label}: building ({node.build_type.value})")
    package.generate()
    package.build()

    described = package.package() or inferred_package(node, backend)
    write_package(
        described,
        package.install_dir,
        store_path,
        node.name,
        node.version,
        build_id,
        backend,
        {
            dependency: stored_components(inputs.dependencies[dependency])
            for dependency in node.dependency_names
        },
        install_prefix=package.context.install_prefix,
        source_dir=dirs.source,
    )


def build_graph(
    root_dir: Path,
    profile: Profile,
    build_type: BuildMode,
    cli_options: dict[str, dict[str, OptionValue]] | None = None,
    cli_sources: dict[str, Path] | None = None,
    debug_all: bool = False,
    report: BuildReport | None = None,
) -> Path:
    """Resolve the root recipe's graph, build it dependencies first, and return the root's path."""
    graph = resolve(root_dir, build_type, cli_options, cli_sources, debug_all, profile=profile)
    if report:
        report.root = graph.root
    validate(graph)
    return _build_nodes(graph, graph.build_order(), profile, report).store_paths[graph.root]


def _build_tools(node: Node, profile: Profile, report: BuildReport | None = None) -> BuiltTools:
    """Build each of a package's tools, which are whole graphs of their own.

    Nothing is shared between them here. The store does that: two tools that need the
    same build of a package get the same store entry.
    """
    packages: dict[str, Path] = {}
    runtime: list[Path] = []
    build_ids: list[str] = []
    for graph in node.tools:
        built = _build_nodes(graph, graph.build_order(), profile, report)
        packages[graph.root] = built.store_paths[graph.root]
        needed_to_run = [graph.root, *graph.transitive_dependencies(graph.root)]
        runtime += [built.store_paths[name] for name in needed_to_run]
        build_ids.append(built.build_ids[graph.root])
    return BuiltTools(packages, tuple(dict.fromkeys(runtime)), tuple(build_ids))


def _inputs_of(
    graph: Graph, node: Node, store_paths: dict[str, Path], tools: BuiltTools
) -> NodeInputs:
    return NodeInputs(
        dependencies={name: store_paths[name] for name in graph.transitive_dependencies(node.name)},
        tools=tools.packages,
        tool_runtime=tools.runtime,
    )


def _build_nodes(
    graph: Graph, nodes: list[Node], profile: Profile, report: BuildReport | None = None
) -> BuiltGraph:
    """Build `nodes`, given dependencies first, each after its own tools."""
    build_ids: dict[str, str] = {}
    store_paths: dict[str, Path] = {}
    for node in nodes:
        tools = _build_tools(node, profile, report)
        build_ids[node.name] = make_build_id(
            node.package,
            node.source,
            profile,
            node.build_type,
            [*(build_ids[name] for name in node.dependency_names), *tools.build_ids],
        )
        inputs = _inputs_of(graph, node, store_paths, tools)
        store_paths[node.name] = build_node(node, build_ids[node.name], profile, inputs, report)
    return BuiltGraph(store_paths, build_ids)


def _build_all_but_root(graph: Graph, profile: Profile) -> NodeInputs:
    """Build everything the root needs and return what its own build would draw on."""
    needed = [node for node in graph.build_order() if node.name != graph.root]
    built = _build_nodes(graph, needed, profile)
    root = graph.nodes[graph.root]
    return _inputs_of(graph, root, built.store_paths, _build_tools(root, profile))


def run_command(
    root_dir: Path,
    profile: Profile,
    command: Sequence[str],
    cli_options: dict[str, dict[str, OptionValue]] | None = None,
    cli_sources: dict[str, Path] | None = None,
    debug_all: bool = False,
) -> int:
    """Run a command in the root's build environment and return its exit code."""
    build_type = BuildMode.Debug if debug_all else BuildMode.Release
    graph = resolve(root_dir, build_type, cli_options, cli_sources, debug_all, profile=profile)
    validate(graph)
    # The command's own output is what the caller wants on stdout
    with contextlib.redirect_stdout(sys.stderr):
        inputs = _build_all_but_root(graph, profile)
    with tempfile.TemporaryDirectory(prefix="silo-run-") as tmp:
        env = build_environment(graph.nodes[graph.root].package, profile, inputs, Path(tmp))
        program = shutil.which(command[0], path=env["PATH"])
        if program is None:
            raise SiloError(f"'{command[0]}' is not on the build PATH of {graph.root}")
        return subprocess.run([program, *command[1:]], env=env, check=False).returncode


def sync_graph(
    root_dir: Path,
    profile: Profile,
    build_types: Sequence[BuildMode],
    cli_options: dict[str, dict[str, OptionValue]] | None = None,
    cli_sources: dict[str, Path] | None = None,
    debug_all: bool = False,
) -> Path:
    """Build the root's dependencies, then let its generate() write into <root>/.silo.

    generate() runs once per build type, each into its own folder, and a build type that is
    not asked for keeps the folder it has. The root itself is not built. Returns <root>/.silo.
    """
    project_generated: Path | None = None
    for build_type in build_types:
        graph = resolve(root_dir, build_type, cli_options, cli_sources, debug_all, profile=profile)
        validate(graph)
        root = graph.nodes[graph.root]
        inputs = _build_all_but_root(graph, profile)

        if project_generated is None:
            project_generated = _prepare_project_dir(root.package.recipe_dir / PROJECT_DIR)
        generated = project_generated / build_type.value
        remove_tree(generated)
        tmp = generated / "tmp"
        tmp.mkdir(parents=True)

        root.package._context = BuildContext(
            profile=profile,
            build_type=build_type,
            env=build_environment(root.package, profile, inputs, tmp),
            source_dir=root.source.local_dir or root.package.recipe_dir,
            build_dir=generated / "build",
            stage_dir=generated / "stage",
            generated_dir=generated,
            install_prefix=(generated / "install").as_posix(),
            local_source=True,
            project_generated_dir=project_generated,
            dependency_packages=inputs.dependencies,
            tool_packages=inputs.tools,
        )
        root.package.generate()
        remove_tree(tmp)
    assert project_generated is not None
    return project_generated


def _prepare_project_dir(project_generated: Path) -> Path:
    """Empty the folder except for the per build type folders, which each sync replaces itself."""
    project_generated.mkdir(exist_ok=True)
    kept = {build_type.value for build_type in BuildMode}
    for item in project_generated.iterdir():
        if item.is_file():
            item.unlink()
        elif item.name not in kept:
            remove_tree(item)
    # The folder ignores itself, so it never shows up in git or in a local source snapshot
    (project_generated / ".gitignore").write_text("*\n", encoding="utf-8")
    return project_generated
