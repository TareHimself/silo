import json
from pathlib import Path


def _package_of(reference: str | dict) -> tuple[str, str]:
    """Split a requirement such as "zlib::zlib" into its package and its full target name."""
    target = reference if isinstance(reference, str) else reference["ref"]
    return target.split("::")[0], target


def _component_target(package_name: str, component_name: str, component: dict, root: Path) -> str:
    target = f"{package_name}::{component_name}"
    artifacts = component["artifacts"]
    libraries = [
        (root / artifact["path"]).as_posix()
        for artifact in artifacts
        if artifact["type"] == "static_lib"
    ]
    include_dirs = [
        (root / artifact["path"]).as_posix()
        for artifact in artifacts
        if artifact["type"] == "headers"
    ]
    required_targets = [_package_of(reference)[1] for reference in component["requires"]]
    link_libraries = [*libraries[1:], *required_targets, *component["system_libs"]]

    properties = {
        "IMPORTED_LOCATION": libraries[:1],
        "INTERFACE_INCLUDE_DIRECTORIES": include_dirs,
        "INTERFACE_COMPILE_DEFINITIONS": component["defines"],
        "INTERFACE_LINK_LIBRARIES": link_libraries,
    }
    kind = "STATIC" if libraries else "INTERFACE"
    lines = [f"if(NOT TARGET {target})", f"  add_library({target} {kind} IMPORTED)"]
    for name, values in properties.items():
        if values:
            lines.append(f'  set_property(TARGET {target} PROPERTY {name} "{";".join(values)}")')
    lines.append("endif()")
    return "\n".join(lines)


def cmake_config(manifest: dict, package_dir: Path) -> str:
    """The text of <name>Config.cmake: one imported target per component, by full path."""
    name = manifest["name"]
    components = manifest["components"]
    other_packages = sorted(
        {
            _package_of(reference)[0]
            for component in components.values()
            for reference in component["requires"]
        }
        - {name}
    )

    sections = ["include(CMakeFindDependencyMacro)"]
    sections += [f"find_dependency({package} CONFIG)" for package in other_packages]
    sections += [
        _component_target(name, component_name, component, package_dir)
        for component_name, component in components.items()
    ]
    return "\n\n".join(sections) + "\n"


def write_dependency_configs(packages: dict[str, Path], out_dir: Path) -> dict[str, Path]:
    """Write a CMake config for each stored package and return each package's config directory."""
    config_dirs = {}
    for name, package_dir in packages.items():
        manifest = json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
        config_dir = out_dir / name
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / f"{name}Config.cmake").write_text(
            cmake_config(manifest, package_dir), encoding="utf-8"
        )
        config_dirs[name] = config_dir
    return config_dirs
