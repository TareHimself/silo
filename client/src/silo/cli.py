from pathlib import Path

import typer

from silo.build_profile import Profile, Settings
from silo.builder import build_graph
from silo.dependency import OptionValue
from silo.dependency_graph import resolve, validate
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.paths import profile_path
from silo.platform import backend_for, get_arch, get_platform

app = typer.Typer()
profile_app = typer.Typer(help="Manage build profiles")
app.add_typer(profile_app, name="profile")

OPTION_HELP = "key=value for the root package, or package:key=value for a dependency"


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


def fail(error: SiloError) -> typer.Exit:
    print(f"error: {error}")
    return typer.Exit(1)


@app.command()
def sync(
    path: Path = typer.Argument(Path("."), help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    debug: bool = typer.Option(False, "--debug"),
):
    """Resolve the graph and print it, without building."""
    build_type = BuildMode.Debug if debug else BuildMode.Release
    try:
        graph = resolve(path.resolve(), build_type, parse_options(options))
        validate(graph)
    except SiloError as error:
        raise fail(error) from error

    for node in graph.build_order():
        options_text = node.package.options.model_dump_json()
        overridden = " (overridden)" if node.overridden else ""
        print(f"{node.name} {node.version} {node.build_type.value} {options_text}{overridden}")
        for dependency in node.dependency_names:
            print(f"  needs {dependency}")


@app.command()
def build(
    path: Path = typer.Argument(Path("."), help="Directory holding the recipe"),
    options: list[str] = typer.Option([], "-o", help=OPTION_HELP),
    profile: str = typer.Option("default", "--profile", "-p"),
    debug: bool = typer.Option(False, "--debug", help="No optimization, hardening on"),
):
    profile_file = profile_path(profile)
    if not profile_file.exists():
        print(f"No profile at {profile_file}. Run `silo profile detect` first.")
        raise typer.Exit(1)
    build_type = BuildMode.Debug if debug else BuildMode.Release
    try:
        build_graph(path.resolve(), Profile.load(profile_file), build_type, parse_options(options))
    except SiloError as error:
        raise fail(error) from error


@profile_app.command()
def detect(
    name: str = typer.Option("default", "--name", "-n"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    path = profile_path(name)
    if path.exists() and not force:
        print(f"Profile already exists at {path}. Pass --force to overwrite it.")
        raise typer.Exit(1)

    os, arch = get_platform(), get_arch()
    profile = Profile(
        settings=Settings(os=os, arch=arch), compiler=backend_for(os).detect_compiler(arch)
    )
    profile.save(path)
    print(f"Wrote {path}")
    print(path.read_text(encoding="utf-8"))
