import pytest

from silo.build_id import compiler_fingerprint, make_build_id, recipe_hash, relevant_settings
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.source import SourceSpec

RELEASE = BuildMode.Release


def fetched(sha256: str = "aa") -> SourceSpec:
    source = SourceSpec()
    source.fetch("https://example.com/demo.tar.gz", sha256)
    return source


def test_c_library_ignores_cxx_settings(load_demo_recipe):
    package = load_demo_recipe('    languages = ("c",)\n')
    assert relevant_settings(package) == ["os", "arch", "compiler", "build_type"]


def test_header_only_ignores_binary_settings(load_demo_recipe):
    package = load_demo_recipe("    header_only = True\n")
    assert relevant_settings(package) == ["cppstd", "libcxx"]


def test_compiler_fingerprint_is_coarse(windows_profile):
    assert compiler_fingerprint(windows_profile) == "msvc-14-x86_64-pc-windows-msvc-10"


def test_build_id_ignores_compiler_patch_version(load_demo_recipe, windows_profile):
    package = load_demo_recipe()
    baseline = make_build_id(package, fetched(), windows_profile, RELEASE)

    windows_profile.compiler.version = "14.52.0"

    assert make_build_id(package, fetched(), windows_profile, RELEASE) == baseline


def test_build_id_changes_with_the_source(load_demo_recipe, windows_profile):
    package = load_demo_recipe()

    assert make_build_id(package, fetched("aa"), windows_profile, RELEASE) != make_build_id(
        package, fetched("bb"), windows_profile, RELEASE
    )


def test_build_id_changes_with_the_build_type(load_demo_recipe, windows_profile):
    package = load_demo_recipe()

    assert make_build_id(package, fetched(), windows_profile, RELEASE) != make_build_id(
        package, fetched(), windows_profile, BuildMode.Debug
    )


def test_build_id_changes_when_a_file_is_added_to_the_recipe(load_demo_recipe, windows_profile):
    package = load_demo_recipe()
    baseline = make_build_id(package, fetched(), windows_profile, RELEASE)

    (package.recipe_dir / "fix.patch").write_text("patch", encoding="utf-8")

    assert make_build_id(package, fetched(), windows_profile, RELEASE) != baseline


def test_a_recipe_with_windows_line_endings_is_refused(load_demo_recipe, windows_profile):
    package = load_demo_recipe()
    recipe = package.recipe_dir / "silopkg.py"
    recipe.write_bytes(recipe.read_bytes().replace(b"\n", b"\r\n"))

    with pytest.raises(SiloError, match="Windows line endings"):
        make_build_id(package, fetched(), windows_profile, RELEASE)


def test_a_local_projects_recipe_hash_is_its_recipe_file_alone(load_demo_recipe):
    package = load_demo_recipe()
    baseline = recipe_hash(package.recipe_dir, local_source=True)

    (package.recipe_dir / "main.cpp").write_text("int main() {}", encoding="utf-8")

    assert recipe_hash(package.recipe_dir, local_source=True) == baseline
    assert recipe_hash(package.recipe_dir, local_source=False) != baseline
