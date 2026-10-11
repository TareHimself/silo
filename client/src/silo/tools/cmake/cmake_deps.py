"""Writes CMake package config files for stored packages, from their package.json.

A consumer's find_package() finds them in any letter case, gets one imported target per
component plus any aliases the consumer declared, and also the older <Name>_LIBRARIES
style variables.
"""

import json
from pathlib import Path
from typing import Any

from silo.errors import SiloError
from silo.silo_package import SiloPackage
from silo.tools.cmake.cmake_generator import CONFIGS_DIR, RUNTIME_FILE


def _package_of(reference: str | dict) -> tuple[str, str]:
    """Split a requirement such as "zlib::zlib" into its package and its full target name."""
    target = reference if isinstance(reference, str) else reference["ref"]
    return target.split("::")[0], target


def _root_variable(package_name: str) -> str:
    """The CMake variable holding a package's folder in the store, for its config and its users."""
    return f"{package_name}_ROOT_DIR"


def _artifact_paths(component: dict, kind: str, root: str) -> list[str]:
    return [
        f"{root}/{artifact['path']}"
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


def _shared_libraries(component: dict, root: str) -> list[dict[str, list[str]]]:
    """Each shared library's file and, where the platform has one, its import library."""
    return [
        {
            "IMPORTED_LOCATION": [f"{root}/{artifact['path']}"],
            "IMPORTED_IMPLIB": [f"{root}/{artifact['import']}"] if "import" in artifact else [],
        }
        for artifact in component["artifacts"]
        if artifact["type"] == "shared_lib"
    ]


def _component_targets(
    package_name: str, component_name: str, component: dict, root: str
) -> list[str]:
    """The component's target, after one helper target for each shared library beyond its first.

    Every shared library needs a target of its own, or CMake's $<TARGET_RUNTIME_DLLS> would
    not list it.
    """
    target = f"{package_name}::{component_name}"
    shared = _shared_libraries(component, root)
    static = _artifact_paths(component, "static_lib", root)
    if shared:
        kind, location, linked_files = "SHARED", shared[0], static
    elif static:
        kind, location, linked_files = "STATIC", {"IMPORTED_LOCATION": static[:1]}, static[1:]
    else:
        kind, location, linked_files = "INTERFACE", {}, []

    helpers = {
        f"{target}_{Path(library['IMPORTED_LOCATION'][0]).stem}": library for library in shared[1:]
    }
    properties = location | {
        "INTERFACE_INCLUDE_DIRECTORIES": _artifact_paths(component, "headers", root),
        "INTERFACE_COMPILE_DEFINITIONS": component["defines"],
        "INTERFACE_LINK_LIBRARIES": [
            *linked_files,
            *helpers,
            *[_package_of(reference)[1] for reference in component["requires"]],
            *component["system_libs"],
        ],
    }
    definitions = [_define_target(name, "SHARED", library) for name, library in helpers.items()]
    return [*definitions, _define_target(target, kind, properties)]


def _has(component: dict, *kinds: str) -> bool:
    return any(artifact["type"] in kinds for artifact in component["artifacts"])


def _is_program(component: dict) -> bool:
    """A component that only ships executables is something to run, not something to link."""
    return _has(component, "executable") and not _has(
        component, "static_lib", "shared_lib", "headers"
    )


def _executable_targets(
    package_name: str, component_name: str, component: dict, root: str
) -> dict[str, str]:
    """An imported executable per program, keyed by target name.

    A component that is one program is named like any component: <package>::<component>.
    Otherwise each program is <package>::<file name without extension>.
    """
    programs = [artifact for artifact in component["artifacts"] if artifact["type"] == "executable"]
    named_by_component = _is_program(component) and len(programs) == 1
    definitions = {}
    for artifact in programs:
        own_name = component_name if named_by_component else Path(artifact["path"]).stem
        target = f"{package_name}::{own_name}"
        location = f"{root}/{artifact['path']}"
        definitions[target] = (
            f"if(NOT TARGET {target})\n"
            f"  add_executable({target} IMPORTED)\n"
            f'  set_property(TARGET {target} PROPERTY IMPORTED_LOCATION "{location}")\n'
            "endif()"
        )
    return definitions


def _legacy_variables(manifest: dict, libraries: dict[str, dict], root: str) -> str:
    """For projects that use ${ZLIB_LIBRARIES} instead of targets, in the caller's own casing."""
    name = "${CMAKE_FIND_PACKAGE_NAME}"
    values = {"VERSION": manifest["version"]}
    if libraries:
        targets = ";".join(f"{manifest['name']}::{component}" for component in libraries)
        include_dirs = ";".join(
            path
            for component in libraries.values()
            for path in _artifact_paths(component, "headers", root)
        )
        values |= {
            "LIBRARIES": targets,
            "LIBRARY": targets,
            "INCLUDE_DIRS": include_dirs,
            "INCLUDE_DIR": include_dirs,
        }
    return "\n".join(f'set({name}_{suffix} "{value}")' for suffix, value in values.items())


def cmake_config(
    manifest: dict,
    package_dir: Path,
    aliases: dict[str, str] | None = None,
    programs_only: bool = False,
) -> str:
    """The text of a package's config file.

    `aliases` maps an extra target name to one of this package's targets, for example
    {"ZLIB::ZLIB": "zlib::zlib"}. `programs_only` is for a package used as a tool: its
    executables become targets and its libraries are left out.
    """
    name = manifest["name"]
    components = manifest["components"]
    libraries = (
        {}
        if programs_only
        else {key: value for key, value in components.items() if not _is_program(value)}
    )
    other_packages = sorted(
        {
            _package_of(reference)[0]
            for component in libraries.values()
            for reference in component["requires"]
        }
        - {name}
    )

    root = f"${{{_root_variable(name)}}}"
    sections = ["include(CMakeFindDependencyMacro)"]
    sections += [f"find_dependency({package} CONFIG)" for package in other_packages]
    sections.append(f'set({_root_variable(name)} "{package_dir.as_posix()}")')
    for component_name, component in libraries.items():
        sections += _component_targets(name, component_name, component, root)
    # A library keeps its name when a program would have had the same one
    taken = {f"{name}::{component_name}" for component_name in libraries}
    for component_name, component in components.items():
        programs = _executable_targets(name, component_name, component, root)
        sections += [text for target, text in programs.items() if target not in taken]
        taken |= set(programs)
    sections += [
        _define_target(alias, "INTERFACE", {"INTERFACE_LINK_LIBRARIES": [target]})
        for alias, target in (aliases or {}).items()
    ]
    sections.append(_legacy_variables(manifest, libraries, root))
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


def _check_aliases(aliases: dict[str, str], manifests: dict[str, dict]) -> None:
    for alias, target in aliases.items():
        package, _, component = target.partition("::")
        if package not in manifests:
            known = ", ".join(sorted(manifests)) or "none"
            raise SiloError(
                f"Alias '{alias}' points at '{target}', but '{package}' is not a dependency "
                f"({known})"
            )
        components = manifests[package]["components"]
        if component not in components:
            raise SiloError(
                f"Alias '{alias}' points at '{target}', but {package} has no component "
                f"'{component}' (it has {', '.join(components)})"
            )


def runtime_libraries(packages: dict[str, Path], manifests: dict[str, dict]) -> list[str]:
    """Every shared library file a program built on these packages has to ship with it.

    On Linux that includes the versioned names, which are what a program asks for.
    """
    files: list[Path] = []
    for name, package_dir in packages.items():
        if manifests[name].get("system_runtime"):
            continue
        for component in manifests[name]["components"].values():
            for artifact in component["artifacts"]:
                if artifact["type"] != "shared_lib":
                    continue
                library = package_dir / artifact["path"]
                names = [
                    sibling
                    for sibling in sorted(library.parent.iterdir())
                    if sibling.is_symlink() and sibling.resolve() == library.resolve()
                ]
                files += [library, *names]
    return [file.as_posix() for file in files]


def write_dependency_configs(
    packages: dict[str, Path],
    prefix_dir: Path,
    aliases: dict[str, str] | None = None,
    tool_packages: dict[str, Path] | None = None,
) -> None:
    """Write config files under `prefix_dir`, which the consumer puts on CMAKE_PREFIX_PATH.

    Files are named in lowercase (zlib/zlib-config.cmake), which CMake matches against
    find_package(zlib), find_package(ZLIB) or any other casing. An alias such as
    "PNG::PNG" for "libpng::libpng" also makes the package findable as PNG. A package in
    `tool_packages` only offers its executables, unless it is also in `packages`.
    The toolchain file loads one more file from here, which sets SILO_RUNTIME_LIBRARIES.
    """
    manifests = {
        name: json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
        for name, package_dir in ((tool_packages or {}) | packages).items()
    }
    _check_aliases(aliases or {}, {name: manifests[name] for name in packages})
    prefix_dir.mkdir(parents=True, exist_ok=True)
    shipped = ";".join(runtime_libraries(packages, manifests))
    (prefix_dir / RUNTIME_FILE).write_text(
        f'set(SILO_RUNTIME_LIBRARIES "{shipped}")\n', encoding="utf-8"
    )
    for name, manifest in manifests.items():
        package_dir = ((tool_packages or {}) | packages)[name]
        own_aliases = {
            alias: target
            for alias, target in (aliases or {}).items()
            if _package_of(target)[0] == name
        }
        config = cmake_config(
            manifest, package_dir, own_aliases, programs_only=name not in packages
        )
        version = cmake_config_version(manifest["version"])

        lookup_names = {name.lower()} | {_package_of(alias)[0].lower() for alias in own_aliases}
        for lookup_name in lookup_names:
            config_dir = prefix_dir / lookup_name
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / f"{lookup_name}-config.cmake").write_text(config, encoding="utf-8")
            (config_dir / f"{lookup_name}-config-version.cmake").write_text(
                version, encoding="utf-8"
            )


class CMakeDeps:
    """Writes a config file per dependency and tool, where the toolchain file looks for them."""

    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package
        self.aliases: dict[str, str] = {}

    def alias(self, name: str, target: str) -> None:
        """Give a dependency's target another name, for build files that expect it.

        alias("ZLIB::ZLIB", "zlib::zlib") also makes find_package(ZLIB) work.
        """
        self.aliases[name] = target

    def generate(self) -> Path:
        context = self.package.context
        configs_dir = context.generated_dir / CONFIGS_DIR
        write_dependency_configs(
            context.dependency_packages, configs_dir, self.aliases, context.tool_packages
        )
        return configs_dir
