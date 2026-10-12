import json
from pathlib import Path

import typer

from silo import cache
from silo.affected import affected_entries, changed_entries
from silo.build_profile import Profile, Settings
from silo.builder import build_graph, run_command, sync_graph
from silo.dependency import OptionValue
from silo.dependency_graph import Graph, resolve, validate
from silo.enums import BuildMode, Compiler
from silo.errors import SiloError
from silo.paths import profile_path
from silo.platform import backend_for, detect_compiler_like, get_arch, get_platform
from silo.report import BuildReport

app = typer.Typer()
profile_app = typer.Typer(help="Manage build profiles")
app.add_typer(profile_app, name="profile")
cache_app = typer.Typer(help="Inspect and clear files silo can recreate")
app.add_typer(cache_app, name="cache")

OPTION_HELP = "key=value for the root package, or package:key=value for a dependency"
REPORT_HELP = (
    "Folder for report.json and one log per package. Command output goes to the logs "
    "instead of the terminal"
)
SOURCE_HELP = "package=path: build that package from a local folder for this run"
DEBUG_HELP = "This package in debug (no optimization, hardening on), dependencies in release"
DEBUG_ALL_HELP = "This package and everything it links in debug. Tools stay release"


@app.callback()
def main():
    """
    SILO package manager
    """


def parse_options(raw: list[str]) -> dict[str, dict[str, OptionValue]]:
    """Group `-o` values by package. Options without a package name go under the key ""."""
    by_package: dict[str, dict[str, OptionValue]] = {}
    for item in raw:
        target, separator, value = item.partition("=")
        if not separator:
            raise SiloError(f"Option '{item}' must look like key=value or package:key=value")
        package, _, key = target.rpartition(":")
        by_package.setdefault(package, {})[key] = value
    return by_package


def parse_sources(raw: list[str]) -> dict[str, Path]:
    """Turn `--source zlib=../zlib` values into absolute folders, relative to where silo runs."""
    sources: dict[str, Path] = {}
    for item in raw:
        package, separator, folder = item.partition("=")
        if not separator or not package or not folder:
            raise SiloError(f"--source '{item}' must look like package=path")
        sources[package] = Path(folder).resolve()
    return sources


def fail(error: SiloError) -> typer.Exit:
    print(f"error: {error}")
    return typer.Exit(1)


def load_profile(name: str) -> Profile:
    profile_file = profile_path(name)
    if not profile_file.exists():
        print(f"No profile at {profile_file}. Run `silo profile detect` first.")
        raise typer.Exit(1)
    return Profile.load(profile_file)


def print_graph(resolved: Graph, indent: str = "") -> None:
    """Each package with what it links, then the graph of every tool it runs, indented."""
    for node in resolved.build_order():
        options_text = node.package.options.model_dump_json()
        overridden = " (overridden)" if node.overridden else ""
        summary = f"{node.name} {node.version} {node.build_type.value} {options_text}"
        print(f"{indent}{summary}{overridden}")
        for dependency in node.dependency_names:
            print(f"{indent}  needs {dependency}")
        for tool in node.tools:
            passed_on = " and passes it on" if tool.transitive else ""
            print(f"{indent}  runs {tool.root}{passed_on}, built from:")
            print_graph(tool, indent + "    ")


@app.command()
def graph(
    path: Path = typer.Argument(Path("."), help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    debug: bool = typer.Option(False, "--debug", help=DEBUG_HELP),
    debug_all: bool = typer.Option(False, "--debug-all", help=DEBUG_ALL_HELP),
    sources: list[str] = typer.Option([], "--source", help=SOURCE_HELP),
    profile: str = typer.Option("default", "--profile", "-p"),
):
    """Resolve the graph and print it, without building."""
    build_type = BuildMode.Debug if debug or debug_all else BuildMode.Release
    try:
        resolved = resolve(
            path.resolve(),
            build_type,
            parse_options(options),
            parse_sources(sources),
            debug_all,
            profile=load_profile(profile),
        )
        validate(resolved)
    except SiloError as error:
        raise fail(error) from error

    print_graph(resolved)


@app.command()
def affected(
    path: Path = typer.Argument(Path("."), help="Directory holding the registry"),
    since: str | None = typer.Option(
        None, "--since", help="A branch, tag or commit to compare the registry with"
    ),
    everything: bool = typer.Option(False, "--all", help="List every recipe"),
    profile_files: list[Path] = typer.Option(
        [], "--profile", "-p", help="A profile file to answer for. The default profile if none"
    ),
):
    """Print the recipes of a registry that a change reaches, as JSON, one list per profile.

    A recipe is reached when it changed, or when anything it links or runs did. Graphs are
    resolved with default options and nothing is built, so a profile file can describe a
    system other than this one. Each list is named after its file.
    """
    root = path.resolve()
    try:
        if everything == bool(since):
            raise SiloError("Give either --since <ref> or --all")
        changed = None if everything else changed_entries(root, since)
        profiles = {file.stem: Profile.load(file) for file in profile_files}
        if not profiles:
            profiles = {"default": load_profile("default")}
        listed = {
            name: [
                entry.relative_to(root).as_posix()
                for entry in affected_entries(root, changed, profile)
            ]
            for name, profile in profiles.items()
        }
    except SiloError as error:
        raise fail(error) from error
    print(json.dumps(listed))


@app.command()
def sync(
    path: Path = typer.Argument(Path("."), help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    profile: str = typer.Option("default", "--profile", "-p"),
    debug: bool = typer.Option(False, "--debug", help="Write only the debug configuration"),
    release: bool = typer.Option(False, "--release", help="Write only the release configuration"),
    debug_all: bool = typer.Option(
        False, "--debug-all", help="Write only the debug configuration, with debug dependencies"
    ),
    sources: list[str] = typer.Option([], "--source", help=SOURCE_HELP),
):
    """Build the dependencies and write the recipe's generated files into its .silo folder.

    Without a flag, both the debug and the release configuration are written.
    """
    try:
        if debug_all and release:
            raise SiloError(
                "--debug-all writes the debug configuration, so it cannot go with --release"
            )
        chosen = [
            build_type
            for build_type, wanted in (
                (BuildMode.Debug, debug or debug_all),
                (BuildMode.Release, release),
            )
            if wanted
        ]
        generated = sync_graph(
            path.resolve(),
            load_profile(profile),
            chosen or [BuildMode.Debug, BuildMode.Release],
            parse_options(options),
            parse_sources(sources),
            debug_all,
        )
    except SiloError as error:
        raise fail(error) from error
    for folder in sorted(item for item in generated.iterdir() if item.is_dir()):
        written = sorted(item.name for item in folder.iterdir())
        print(f"{folder}: {', '.join(written)}")


@app.command()
def build(
    path: Path = typer.Argument(Path("."), help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    profile: str = typer.Option("default", "--profile", "-p"),
    debug: bool = typer.Option(False, "--debug", help=DEBUG_HELP),
    debug_all: bool = typer.Option(False, "--debug-all", help=DEBUG_ALL_HELP),
    sources: list[str] = typer.Option([], "--source", help=SOURCE_HELP),
    report_dir: Path | None = typer.Option(None, "--report", help=REPORT_HELP),
):
    """Build the recipe and its dependencies into the store."""
    loaded_profile = load_profile(profile)
    build_type = BuildMode.Debug if debug or debug_all else BuildMode.Release
    report = BuildReport(report_dir) if report_dir else None
    try:
        store_path = build_graph(
            path.resolve(),
            loaded_profile,
            build_type,
            parse_options(options),
            parse_sources(sources),
            debug_all,
            report,
        )
    except Exception as error:
        if report:
            print(f"report: {report.write(error=error)}")
        if isinstance(error, SiloError):
            raise fail(error) from error
        raise
    if report:
        print(f"report: {report.write(store_path)}")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    context: typer.Context,
    path: Path = typer.Option(Path("."), "--project", "-C", help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    profile: str = typer.Option("default", "--profile", "-p"),
    debug_all: bool = typer.Option(False, "--debug-all", help=DEBUG_ALL_HELP),
    sources: list[str] = typer.Option([], "--source", help=SOURCE_HELP),
):
    """Run a command with the recipe's compiler, tools and dependencies set up.

    For example: silo run -- cmake --preset zapp-debug
    """
    if not context.args:
        raise fail(SiloError("Give a command to run, for example: silo run -- cmake --version"))
    try:
        exit_code = run_command(
            path.resolve(),
            load_profile(profile),
            context.args,
            parse_options(options),
            parse_sources(sources),
            debug_all,
        )
    except SiloError as error:
        raise fail(error) from error
    raise typer.Exit(exit_code)


@profile_app.command()
def detect(
    name: str = typer.Option("default", "--name", "-n"),
    force: bool = typer.Option(False, "--force", "-f"),
    compiler: Compiler | None = typer.Option(
        None, "--compiler", help="The compiler to look for, where a system has several"
    ),
    matching: Path | None = typer.Option(
        None,
        "--matching",
        help="A profile file. Fail unless this machine has its kind of compiler, in a "
        "version whose binaries mix with it",
    ),
):
    path = profile_path(name)
    if path.exists() and not force:
        print(f"Profile already exists at {path}. Pass --force to overwrite it.")
        raise typer.Exit(1)

    os, arch = get_platform(), get_arch()
    try:
        if matching and compiler:
            raise SiloError(
                "--matching names the compiler already, so --compiler cannot go with it"
            )
        settings = Settings(os=os, arch=arch)
        if matching:
            wanted = Profile.load(matching)
            found = detect_compiler_like(wanted)
            # The file is the whole configuration, so its standard and C++ library are kept
            settings = wanted.settings.model_copy(update={"os": os, "arch": arch})
        else:
            found = backend_for(os).detect_compiler(arch, compiler)
    except SiloError as error:
        raise fail(error) from error
    profile = Profile(settings=settings, compiler=found)
    profile.save(path)
    print(f"Wrote {path}")
    print(path.read_text(encoding="utf-8"))


@cache_app.command("list")
def list_caches():
    """Show each cache, its size and where it is."""
    for entry in cache.CACHES:
        size = cache.format_size(cache.size_of(entry.directory()))
        print(f"{entry.name:<10} {size:>10}  {entry.description}  ({entry.directory()})")


@cache_app.command("clear")
def clear_caches(
    names: list[str] = typer.Argument(None, help="Caches to clear. All of them when left out."),
):
    """Delete caches. Built packages in the store are kept."""
    try:
        chosen = cache.find_caches(names or [])
    except SiloError as error:
        raise fail(error) from error
    for entry in chosen:
        print(f"cleared {entry.name} ({cache.format_size(cache.clear(entry))})")
