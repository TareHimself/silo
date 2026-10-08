import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import xxhash

from silo.errors import SiloError
from silo.platform.base import PlatformBackend
from silo.source import sha256_of

SCHEMA = 1


@dataclass
class SharedLib:
    path: str
    import_lib: str | None = None


@dataclass
class Requirement:
    ref: str
    headers: bool = True


@dataclass
class Component:
    name: str
    headers: Sequence[str] = ()
    static_libs: Sequence[str] = ()
    shared_libs: Sequence[SharedLib] = ()
    executables: Sequence[str] = ()
    content: Sequence[str] = ()
    # What consumers must also link. "zlib" is a whole package and "zlib::zlib" one of its
    # components; a component of this package is "<package>::<name>". Nothing is implied.
    requires: Sequence[str | Requirement] = ()
    defines: Sequence[str] = ()
    system_libs: Sequence[str] = ()
    build_modules: Sequence[str] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Package:
    components: list[Component]

    @classmethod
    def infer(cls, install_dir: Path, name: str, backend: PlatformBackend) -> "Package":
        """One component from the conventional layout. Refuses to guess a link order."""
        libs = _files_with_suffix(install_dir / "lib", backend.static_lib_suffixes)
        if len(libs) > 1:
            found = ", ".join(lib.name for lib in libs)
            raise RuntimeError(
                f"Cannot infer the package for '{name}': lib/ holds several libraries ({found}). "
                "Add a package() hook."
            )
        executables = _files_with_suffix(install_dir / "bin", backend.executable_suffixes)
        component = Component(
            name,
            headers=["include"] if (install_dir / "include").is_dir() else [],
            static_libs=[f"lib/{lib.name}" for lib in libs],
            executables=[f"bin/{executable.name}" for executable in executables],
            content=["share"] if (install_dir / "share").is_dir() else [],
        )
        return cls(components=[component])


def _files_with_suffix(directory: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.suffix in suffixes)


def _tree_hash(root: Path) -> str:
    tree = xxhash.xxh128()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            tree.update(path.relative_to(root).as_posix().encode())
            tree.update(sha256_of(path).encode())
    return f"tree:{tree.hexdigest()}"


def _find_file(install_dir: Path, name: str, candidates: Sequence[str] = ()) -> str:
    """`name` is either a path that exists as given, or a bare name tried against candidates."""
    tried = [name, *candidates]
    for relative in tried:
        if (install_dir / relative).is_file():
            return relative
    raise RuntimeError(f"'{name}' was not found in {install_dir} (tried {', '.join(tried)})")


def _find_directory(install_dir: Path, relative: str) -> str:
    if not (install_dir / relative).is_dir():
        raise RuntimeError(f"Directory '{relative}' was not found in {install_dir}")
    return relative


def _file_artifact(kind: str, install_dir: Path, relative: str) -> dict:
    return {
        "type": kind,
        "name": Path(relative).stem,
        "path": relative,
        "hash": sha256_of(install_dir / relative),
    }


def _directory_artifact(kind: str, install_dir: Path, relative: str) -> dict:
    return {"type": kind, "path": relative, "hash": _tree_hash(install_dir / relative)}


def _component_artifacts(
    component: Component, install_dir: Path, backend: PlatformBackend
) -> list[dict]:
    artifacts = []
    for directory in component.headers:
        relative = _find_directory(install_dir, directory)
        artifacts.append(_directory_artifact("headers", install_dir, relative))
    for name in component.static_libs:
        relative = _find_file(install_dir, name, backend.static_lib_candidates(name))
        artifacts.append(_file_artifact("static_lib", install_dir, relative))
    for shared_lib in component.shared_libs:
        artifact = _file_artifact(
            "shared_lib", install_dir, _find_file(install_dir, shared_lib.path)
        )
        if shared_lib.import_lib:
            artifact["import"] = _find_file(install_dir, shared_lib.import_lib)
        artifacts.append(artifact)
    for name in component.executables:
        relative = _find_file(install_dir, name, backend.executable_candidates(name))
        artifacts.append(_file_artifact("executable", install_dir, relative))
    for directory in component.content:
        relative = _find_directory(install_dir, directory)
        artifacts.append(_directory_artifact("content", install_dir, relative))
    for module in component.build_modules:
        relative = _find_file(install_dir, module)
        artifacts.append(
            {"type": "cmake_module", "path": relative, "hash": sha256_of(install_dir / relative)}
        )
    return artifacts


def stored_components(package_dir: Path) -> list[str]:
    """The component names of a package already in the store."""
    manifest = json.loads((package_dir / "silo" / "package.json").read_text(encoding="utf-8"))
    return list(manifest["components"])


def _targets_of(reference: str, known: dict[str, list[str]], required_by: str) -> list[str]:
    """Expand "zlib" to all of zlib's components, and check "zlib::zlib" names a real one."""
    package, separator, component = reference.partition("::")
    if package not in known:
        raise SiloError(
            f"{required_by} requires '{reference}', but '{package}' is neither this package "
            f"nor one of its direct dependencies ({', '.join(sorted(known)) or 'none'})"
        )
    if not separator:
        return [f"{package}::{name}" for name in known[package]]
    if component not in known[package]:
        raise SiloError(
            f"{required_by} requires '{reference}', but {package} has no component "
            f"'{component}' (it has {', '.join(known[package])})"
        )
    return [reference]


def _resolved_requires(
    component: Component,
    package_name: str,
    own_components: list[str],
    dependency_components: dict[str, list[str]],
) -> list[str | dict]:
    known = dependency_components | {package_name: own_components}
    required_by = f"{package_name}::{component.name}"
    resolved: list[str | dict] = []
    for requirement in component.requires:
        if isinstance(requirement, str):
            resolved += _targets_of(requirement, known, required_by)
        else:
            resolved += [
                {"ref": target, "headers": requirement.headers}
                for target in _targets_of(requirement.ref, known, required_by)
            ]
    return resolved


def _component_manifest(
    component: Component, artifacts: list[dict], requires: list[str | dict]
) -> dict:
    return {
        "artifacts": artifacts,
        "requires": requires,
        "defines": list(component.defines),
        "system_libs": list(component.system_libs),
        "env": component.env,
    }


def _copy_into(package_dir: Path, install_dir: Path, relative: str) -> None:
    source, target = install_dir / relative, package_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def _file_hashes(package_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(package_dir).as_posix(): sha256_of(path)
        for path in sorted(package_dir.rglob("*"))
        if path.is_file()
    }


def write_package(
    package: Package,
    install_dir: Path,
    store_path: Path,
    name: str,
    version: str,
    build_id: str,
    backend: PlatformBackend,
    dependency_components: dict[str, list[str]] | None = None,
) -> None:
    """Copy only what the components list into the store and write silo/package.json.

    `dependency_components` maps each direct dependency to its component names.
    """
    own_components = [component.name for component in package.components]
    staging = store_path.with_name(f".tmp-{store_path.name}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    components = {}
    for component in package.components:
        artifacts = _component_artifacts(component, install_dir, backend)
        for artifact in artifacts:
            _copy_into(staging, install_dir, artifact["path"])
            if "import" in artifact:
                _copy_into(staging, install_dir, artifact["import"])
        requires = _resolved_requires(component, name, own_components, dependency_components or {})
        components[component.name] = _component_manifest(component, artifacts, requires)

    manifest = {
        "schema": SCHEMA,
        "name": name,
        "version": version,
        "id": build_id,
        "components": components,
        "files": _file_hashes(staging),
    }
    manifest_file = staging / "silo" / "package.json"
    manifest_file.parent.mkdir()
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    staging.rename(store_path)
