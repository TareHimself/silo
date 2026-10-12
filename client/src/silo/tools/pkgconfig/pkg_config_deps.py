"""Writes pkg-config files for stored packages, from their package.json.

One .pc file per component, named after the component, plus any aliases the consumer
declared. Build systems that look dependencies up through pkg-config, such as Meson, then
find silo's packages and nothing installed on the machine.
"""

import json
from pathlib import Path
from typing import Any

from silo.errors import SiloError
from silo.package import framework_flags
from silo.silo_package import SiloPackage

PC_DIR = "pkgconfig"
LINKED = ("static_lib", "shared_lib")


def _pc_names(manifests: dict[str, dict]) -> dict[str, str]:
    """Every known target, such as "zlib::zlib", to the name of its .pc file."""
    return {
        f"{package}::{name}": name
        for package, manifest in manifests.items()
        for name in manifest["components"]
    }


def _variables(manifest: dict, component: dict, package_dir: Path) -> dict[str, str]:
    """The folders builds conventionally ask for, and where each of the programs is."""
    variables = {
        "prefix": package_dir.as_posix(),
        "bindir": "${prefix}/bin",
        "libdir": "${prefix}/lib",
        "includedir": "${prefix}/include",
        "datadir": "${prefix}/share",
        "pkgdatadir": f"${{datadir}}/{manifest['name']}",
    }
    for artifact in component["artifacts"]:
        if artifact["type"] == "executable":
            program = Path(artifact["path"]).stem.replace("-", "_")
            variables[program] = f"${{prefix}}/{artifact['path']}"
    return variables


def pc_text(
    manifest: dict,
    component_name: str,
    package_dir: Path,
    names: dict[str, str],
    name: str | None = None,
) -> str:
    """The .pc file of one component. `name` is for an alias, which is the same file renamed."""
    component = manifest["components"][component_name]
    artifacts = component["artifacts"]
    includes = [f"-I${{prefix}}/{a['path']}" for a in artifacts if a["type"] == "headers"]
    defines = [f"-D{define}" for define in component["defines"]]
    libraries = [
        f"${{prefix}}/{a.get('import', a['path'])}" for a in artifacts if a["type"] in LINKED
    ]
    system = [f"-l{library}" for library in component["system_libs"]]
    system += framework_flags(component)
    requires = [
        names[target]
        for requirement in component["requires"]
        if (target := requirement if isinstance(requirement, str) else requirement["ref"]) in names
    ]
    variables = _variables(manifest, component, package_dir)
    lines = [f"{key}={value}" for key, value in variables.items()]
    lines += [
        "",
        f"Name: {name or component_name}",
        f"Description: {manifest['name']}::{component_name}, from silo",
        f"Version: {manifest['version']}",
        f"Requires: {' '.join(requires)}",
        f"Cflags: {' '.join(includes + defines)}",
        f"Libs: {' '.join(libraries + system)}",
    ]
    return "\n".join(lines) + "\n"


def _alias_target(alias: str, target: str, manifests: dict[str, dict]) -> tuple[str, str]:
    package, _, component = target.partition("::")
    if package not in manifests:
        known = ", ".join(sorted(manifests)) or "none"
        raise SiloError(
            f"Alias '{alias}' points at '{target}', but '{package}' is not a dependency ({known})"
        )
    components = manifests[package]["components"]
    if component not in components:
        raise SiloError(
            f"Alias '{alias}' points at '{target}', but {package} has no component "
            f"'{component}' (it has {', '.join(components)})"
        )
    return package, component


def write_pc_files(
    packages: dict[str, Path], pc_dir: Path, aliases: dict[str, str] | None = None
) -> None:
    """`aliases` maps an extra file name to a target: {"freetype2": "freetype::freetype"}."""
    manifests = {
        name: json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
        for name, package_dir in packages.items()
    }
    names = _pc_names(manifests)
    files = {
        component: pc_text(manifest, component, packages[package], names)
        for package, manifest in manifests.items()
        for component in manifest["components"]
    }
    for alias, target in (aliases or {}).items():
        package, component = _alias_target(alias, target, manifests)
        files[alias] = pc_text(manifests[package], component, packages[package], names, alias)

    pc_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (pc_dir / f"{name}.pc").write_text(text, encoding="utf-8", newline="\n")


class PkgConfigDeps:
    """Writes a .pc file for every component of this build's dependencies and tools.

    `aliases` is for a build that asks for a library under another name than silo's, in
    place of editing that build: {"freetype2": "freetype::freetype"}.
    """

    def __init__(self, package: SiloPackage[Any], aliases: dict[str, str] | None = None) -> None:
        self.package = package
        self.aliases = aliases or {}

    def generate(self) -> Path:
        context = self.package.context
        pc_dir = context.generated_dir / PC_DIR
        packages = context.tool_packages | context.dependency_packages
        write_pc_files(packages, pc_dir, self.aliases)
        return pc_dir
