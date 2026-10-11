"""Writes pkg-config files for stored packages, from their package.json.

One .pc file per component, named by the component's pkg_config name, which defaults to
the component's own name. Build systems that look dependencies up through pkg-config,
such as Meson, then find silo's packages and nothing installed on the machine.
"""

import json
from pathlib import Path
from typing import Any

from silo.silo_package import SiloPackage

PC_DIR = "pkgconfig"
LINKED = ("static_lib", "shared_lib")


def pc_name(component_name: str, component: dict) -> str:
    return component.get("pkg_config", {}).get("name") or component_name


def _pc_names(manifests: dict[str, dict]) -> dict[str, str]:
    """Every known target, such as "zlib::zlib", to the name of its .pc file."""
    return {
        f"{package}::{name}": pc_name(name, component)
        for package, manifest in manifests.items()
        for name, component in manifest["components"].items()
    }


def pc_text(manifest: dict, component_name: str, package_dir: Path, names: dict[str, str]) -> str:
    component = manifest["components"][component_name]
    artifacts = component["artifacts"]
    includes = [f"-I${{prefix}}/{a['path']}" for a in artifacts if a["type"] == "headers"]
    defines = [f"-D{define}" for define in component["defines"]]
    libraries = [
        f"${{prefix}}/{a.get('import', a['path'])}" for a in artifacts if a["type"] in LINKED
    ]
    system = [f"-l{library}" for library in component["system_libs"]]
    requires = [
        names[target]
        for requirement in component["requires"]
        if (target := requirement if isinstance(requirement, str) else requirement["ref"]) in names
    ]
    pkg_config = component.get("pkg_config", {})
    variables = pkg_config.get("variables", {})
    lines = [f"prefix={package_dir.as_posix()}"]
    lines += [f"{key}={value}" for key, value in variables.items()]
    lines += [
        "",
        f"Name: {pc_name(component_name, component)}",
        f"Description: {manifest['name']}::{component_name}, from silo",
        f"Version: {pkg_config.get('version') or manifest['version']}",
        f"Requires: {' '.join(requires)}",
        f"Cflags: {' '.join(includes + defines)}",
        f"Libs: {' '.join(libraries + system)}",
    ]
    return "\n".join(lines) + "\n"


def write_pc_files(packages: dict[str, Path], pc_dir: Path) -> None:
    manifests = {
        name: json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
        for name, package_dir in packages.items()
    }
    names = _pc_names(manifests)
    pc_dir.mkdir(parents=True, exist_ok=True)
    for name, manifest in manifests.items():
        for component_name, component in manifest["components"].items():
            text = pc_text(manifest, component_name, packages[name], names)
            pc_file = pc_dir / f"{pc_name(component_name, component)}.pc"
            pc_file.write_text(text, encoding="utf-8", newline="\n")


class PkgConfigDeps:
    """Writes a .pc file for every component of this build's dependencies and tools."""

    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package

    def generate(self) -> Path:
        context = self.package.context
        pc_dir = context.generated_dir / PC_DIR
        write_pc_files(context.tool_packages | context.dependency_packages, pc_dir)
        return pc_dir
