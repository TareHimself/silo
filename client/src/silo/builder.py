import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import xxhash

from silo.build_context import BuildContext
from silo.build_id import compiler_fingerprint, make_build_id, recipe_tree_hash
from silo.build_profile import Profile
from silo.dependency import OptionValue
from silo.dependency_graph import Node, resolve, validate
from silo.enums import BuildMode
from silo.git_snapshot import checkout_tree
from silo.package import Package, write_package
from silo.paths import store_dir, work_dir
from silo.platform import backend_for
from silo.source import SourceTree, unpack_fetched
from silo.tool_resolver import resolve_tool


@dataclass(frozen=True)
class WorkDirs:
    root: Path

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
            unpack_fetched(source, dirs.source)
            package.patch(tree)
        return

    assert source.local_dir is not None and source.tree is not None
    wanted = {"tree": source.tree, "recipe": recipe_tree_hash(package.recipe_dir)}
    if dirs.source_state.exists() and json.loads(dirs.source_state.read_text()) == wanted:
        return
    checkout_tree(source.local_dir, source.tree, dirs.source, dirs.source_index)
    package.patch(tree)
    dirs.source_state.write_text(json.dumps(wanted))


def build_node(
    node: Node, build_id: str, profile: Profile, dependency_packages: dict[str, Path]
) -> Path:
    """Build one package into the store and return its store path. A store hit builds nothing."""
    package = node.package
    label = f"{node.name}-{node.version}-{build_id}"
    store_path = store_dir() / label
    if store_path.exists():
        print(f"{label}: already in the store")
        return store_path

    backend = backend_for(profile.settings.os)
    tools = [resolve_tool(tool) for tool in package._declared_tools]
    key = work_key(node, build_id, profile)
    dirs = WorkDirs(work_dir() / f"{node.name}-{key}")
    dirs.reset_scratch()

    package._context = BuildContext(
        profile=profile,
        build_type=node.build_type,
        env=backend.build_env(profile, [tool.bin_dir for tool in tools], dirs.tmp),
        source_dir=dirs.source,
        build_dir=dirs.build,
        stage_dir=dirs.stage,
        generated_dir=dirs.generated,
        install_prefix=f"/silo-prefix-{key}",
        local_source=node.source.local_source,
        dependency_packages=dependency_packages,
    )

    print(f"{label}: preparing source")
    prepare_source(node, dirs)

    print(f"{label}: building ({node.build_type.value})")
    package.build()

    described = package.package() or Package.infer(package.install_dir, node.name, backend)
    write_package(
        described,
        package.install_dir,
        store_path,
        node.name,
        node.version,
        build_id,
        backend,
    )
    print(f"{label}: stored at {store_path}")
    return store_path


def build_graph(
    root_dir: Path,
    profile: Profile,
    build_type: BuildMode,
    cli_options: dict[str, dict[str, OptionValue]] | None = None,
) -> Path:
    """Resolve the root recipe's graph, build it dependencies first, and return the root's path."""
    graph = resolve(root_dir, build_type, cli_options)
    validate(graph)

    build_ids: dict[str, str] = {}
    store_paths: dict[str, Path] = {}
    for node in graph.build_order():
        build_ids[node.name] = make_build_id(
            node.package,
            node.source,
            profile,
            node.build_type,
            [build_ids[dependency] for dependency in node.dependency_names],
        )
        dependency_packages = {
            dependency: store_paths[dependency]
            for dependency in graph.transitive_dependencies(node.name)
        }
        store_paths[node.name] = build_node(
            node, build_ids[node.name], profile, dependency_packages
        )
    return store_paths[graph.root]
