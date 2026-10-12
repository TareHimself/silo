from collections.abc import Iterable, Iterator
from pathlib import Path

import xxhash

from silo.build_profile import Profile
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.silo_package import SiloPackage
from silo.source import SourceSpec

# Bump only when silo's build helpers change what a build produces
HELPERS_VERSION = "5"

ALL_SETTINGS = ("os", "arch", "compiler", "build_type", "cppstd", "libcxx")
CXX_ONLY_SETTINGS = {"cppstd", "libcxx"}
BINARY_SETTINGS = {"os", "arch", "compiler", "build_type"}
IGNORED_RECIPE_DIRS = {"__pycache__", ".silo", ".venv"}
RECIPE_FILE = "silopkg.py"


def _recipe_files(recipe_dir: Path) -> Iterator[Path]:
    for path in sorted(recipe_dir.rglob("*")):
        relative = path.relative_to(recipe_dir)
        if path.is_file() and not IGNORED_RECIPE_DIRS.intersection(relative.parts):
            yield relative


def _recipe_bytes(file: Path) -> bytes:
    content = file.read_bytes()
    # A file with a zero byte is not text, so it has no line endings to speak of
    if b"\r\n" in content and b"\0" not in content:
        raise SiloError(
            f"{file} has Windows line endings (CRLF). Save it with LF, so the recipe has the "
            "same hash on every machine."
        )
    return content


def recipe_hash(recipe_dir: Path, local_source: bool) -> str:
    """Covers the recipe file and, for a recipe in a registry, the patches and helpers beside it.

    A recipe that builds a local folder sits in the project it builds, whose files the
    source snapshot already covers. Only its silopkg.py counts here.
    """
    files = [Path(RECIPE_FILE)] if local_source else _recipe_files(recipe_dir)
    tree = xxhash.xxh128()
    for relative in files:
        tree.update(relative.as_posix().encode())
        tree.update(_recipe_bytes(recipe_dir / relative))
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
    parts = [compiler.kind.value, compiler.generation, compiler.target]
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
    inputs.update(recipe_hash(package.recipe_dir, source.holds_the_recipe).encode())
    inputs.update(source.id.encode())
    inputs.update(HELPERS_VERSION.encode())
    for setting in relevant_settings(package):
        inputs.update(f"{setting}={setting_value(profile, build_type, setting)}".encode())
    inputs.update(package.options.model_dump_json().encode())
    for dependency_id in sorted(dependency_ids):
        inputs.update(dependency_id.encode())
    return inputs.hexdigest()[:16]
