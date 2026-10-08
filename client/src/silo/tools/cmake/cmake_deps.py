"""Writes CMake package config files for stored packages, from their package.json.

A consumer's find_package() finds them in any letter case, gets one imported target per
component plus any aliases the consumer declared, and also the older <Name>_LIBRARIES
style variables.
"""

import json
from pathlib import Path


def _package_of(reference: str | dict) -> tuple[str, str]:
    """Split a requirement such as "zlib::zlib" into its package and its full target name."""
    target = reference if isinstance(reference, str) else reference["ref"]
    return target.split("::")[0], target


def _artifact_paths(component: dict, kind: str, root: Path) -> list[str]:
    return [
        (root / artifact["path"]).as_posix()
        for artifact in component["artifacts"]
        if artifact["type"] == kind
    ]


def _define_target(target: str, kind: str, properties: dict[str, list[str]]) -> str:
    lines = [f"if(NOT TARGET {target})", f"  add_library({target} {kind} IMPORTED)"]
    for name, values in properties.items():
        if values:
            lines.append(f'  set_property(TARGET {target} PROPERTY {name} "{";".join(values)}")')
    lines.append("endif()")
    return "\n".join(lines)


def _component_target(package_name: str, component_name: str, component: dict, root: Path) -> str:
    libraries = _artifact_paths(component, "static_lib", root)
    required_targets = [_package_of(reference)[1] for reference in component["requires"]]
    properties = {
        "IMPORTED_LOCATION": libraries[:1],
        "INTERFACE_INCLUDE_DIRECTORIES": _artifact_paths(component, "headers", root),
        "INTERFACE_COMPILE_DEFINITIONS": component["defines"],
        "INTERFACE_LINK_LIBRARIES": [
            *libraries[1:],
            *required_targets,
            *component["system_libs"],
        ],
    }
    kind = "STATIC" if libraries else "INTERFACE"
    return _define_target(f"{package_name}::{component_name}", kind, properties)


def _legacy_variables(manifest: dict, package_dir: Path) -> str:
    """For projects that use ${ZLIB_LIBRARIES} instead of targets, in the caller's own casing."""
    targets = [f"{manifest['name']}::{name}" for name in manifest["components"]]
    include_dirs = [
        path
        for component in manifest["components"].values()
        for path in _artifact_paths(component, "headers", package_dir)
    ]
    name = "${CMAKE_FIND_PACKAGE_NAME}"
    values = {
        "VERSION": manifest["version"],
        "LIBRARIES": ";".join(targets),
        "LIBRARY": ";".join(targets),
        "INCLUDE_DIRS": ";".join(include_dirs),
        "INCLUDE_DIR": ";".join(include_dirs),
    }
    return "\n".join(f'set({name}_{suffix} "{value}")' for suffix, value in values.items())


def cmake_config(manifest: dict, package_dir: Path, aliases: dict[str, str] | None = None) -> str:
    """The text of a package's config file.

    `aliases` maps an extra target name to one of this package's targets, for example
    {"ZLIB::ZLIB": "zlib::zlib"}.
    """
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
    sections += [
        _define_target(alias, "INTERFACE", {"INTERFACE_LINK_LIBRARIES": [target]})
        for alias, target in (aliases or {}).items()
    ]
    sections.append(_legacy_variables(manifest, package_dir))
    return "\n\n".join(sections) + "\n"


def cmake_config_version(version: str) -> str:
    """Accept any request for this version or older, so find_package(ZLIB 1.2) works."""
    return (
        f'set(PACKAGE_VERSION "{version}")\n'
        "if(PACKAGE_FIND_VERSION VERSION_GREATER PACKAGE_VERSION)\n"
        "  set(PACKAGE_VERSION_COMPATIBLE FALSE)\n"
        "else()\n"
        "  set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "endif()\n"
    )


def write_dependency_configs(
    packages: dict[str, Path], prefix_dir: Path, aliases: dict[str, str] | None = None
) -> None:
    """Write config files under `prefix_dir`, which the consumer puts on CMAKE_PREFIX_PATH.

    Files are named in lowercase (zlib/zlib-config.cmake), which CMake matches against
    find_package(zlib), find_package(ZLIB) or any other casing. An alias such as
    "PNG::PNG" for "libpng::libpng" also makes the package findable as PNG.
    """
    for name, package_dir in packages.items():
        manifest = json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
        own_aliases = {
            alias: target
            for alias, target in (aliases or {}).items()
            if _package_of(target)[0] == name
        }
        config = cmake_config(manifest, package_dir, own_aliases)
        version = cmake_config_version(manifest["version"])

        lookup_names = {name.lower()} | {_package_of(alias)[0].lower() for alias in own_aliases}
        for lookup_name in lookup_names:
            config_dir = prefix_dir / lookup_name
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / f"{lookup_name}-config.cmake").write_text(config, encoding="utf-8")
            (config_dir / f"{lookup_name}-config-version.cmake").write_text(
                version, encoding="utf-8"
            )
