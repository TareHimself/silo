from collections.abc import Iterable, Iterator
from pathlib import Path

import xxhash

from silo.build_profile import Profile
from silo.enums import BuildMode
from silo.git_snapshot import find_repo, snapshot_tree
from silo.silo_package import SiloPackage
from silo.source import SourceSpec

# Bump only when silo's build helpers change what a build produces
HELPERS_VERSION = "4"

ALL_SETTINGS = ("os", "arch", "compiler", "build_type", "cppstd", "libcxx")
CXX_ONLY_SETTINGS = {"cppstd", "libcxx"}
BINARY_SETTINGS = {"os", "arch", "compiler", "build_type"}
IGNORED_RECIPE_DIRS = {"__pycache__", ".silo", ".venv"}


def _recipe_files(recipe_dir: Path) -> Iterator[Path]:
    for path in sorted(recipe_dir.rglob("*")):
        relative = path.relative_to(recipe_dir)
        if path.is_file() and not IGNORED_RECIPE_DIRS.intersection(relative.parts):
            yield relative


def recipe_tree_hash(recipe_dir: Path) -> str:
    """Covers the recipe, its patches and helpers. Uses git where it can, to honor .gitignore."""
    if find_repo(recipe_dir) is not None:
        return snapshot_tree(recipe_dir)

    tree = xxhash.xxh128()
    for relative in _recipe_files(recipe_dir):
        tree.update(relative.as_posix().encode())
        tree.update((recipe_dir / relative).read_bytes())
    return tree.hexdigest()


def relevant_settings(package: SiloPackage) -> list[str]:
    ignored = set(package.ignore_settings)
    if package.is_c_only:
        ignored |= CXX_ONLY_SETTINGS
    if package.header_only:
        ignored |= BINARY_SETTINGS
    return [setting for setting in ALL_SETTINGS if setting not in ignored]


def compiler_fingerprint(profile: Profile) -> str:
    """Coarse on purpose, so a prebuilt matches across patch releases of a compiler."""
    compiler = profile.compiler
    parts = [compiler.kind.value, compiler.version.split(".")[0], compiler.target]
    if compiler.sdk:
        parts.append(compiler.sdk.split(".")[0])
    return "-".join(parts)


def setting_value(profile: Profile, build_type: BuildMode, setting: str) -> str:
    if setting == "compiler":
        return compiler_fingerprint(profile)
    if setting == "build_type":
        return build_type.value
    value = getattr(profile.settings, setting)
    return str(getattr(value, "value", value))


def make_build_id(
    package: SiloPackage,
    source: SourceSpec,
    profile: Profile,
    build_type: BuildMode,
    dependency_ids: Iterable[str] = (),
) -> str:
    inputs = xxhash.xxh128()
    inputs.update(recipe_tree_hash(package.recipe_dir).encode())
    inputs.update(source.id.encode())
    inputs.update(HELPERS_VERSION.encode())
    for setting in relevant_settings(package):
        inputs.update(f"{setting}={setting_value(profile, build_type, setting)}".encode())
    inputs.update(package.options.model_dump_json().encode())
    for dependency_id in sorted(dependency_ids):
        inputs.update(dependency_id.encode())
    return inputs.hexdigest()[:16]
