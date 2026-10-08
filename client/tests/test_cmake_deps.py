import json
from pathlib import Path

from silo.tools.cmake.cmake_deps import cmake_config, write_dependency_configs

MANIFEST = {
    "name": "freetype",
    "version": "2.13.3",
    "components": {
        "freetype": {
            "artifacts": [
                {"type": "headers", "path": "include/freetype2"},
                {"type": "static_lib", "path": "lib/freetype.lib"},
            ],
            "requires": ["zlib::zlib", {"ref": "freetype::base", "headers": False}],
            "defines": ["FT_STATIC"],
            "system_libs": ["ws2_32"],
        },
        "base": {"artifacts": [], "requires": [], "defines": [], "system_libs": []},
    },
}
STORE = Path("/store/freetype-1")


def test_config_imports_each_component_by_full_path():
    config = cmake_config(MANIFEST, STORE)

    assert "add_library(freetype::freetype STATIC IMPORTED)" in config
    assert 'PROPERTY IMPORTED_LOCATION "/store/freetype-1/lib/freetype.lib"' in config
    assert 'PROPERTY INTERFACE_INCLUDE_DIRECTORIES "/store/freetype-1/include/freetype2"' in config
    assert 'PROPERTY INTERFACE_COMPILE_DEFINITIONS "FT_STATIC"' in config
    assert 'PROPERTY INTERFACE_LINK_LIBRARIES "zlib::zlib;freetype::base;ws2_32"' in config


def test_config_finds_other_packages_but_not_itself():
    config = cmake_config(MANIFEST, STORE)

    assert "find_dependency(zlib CONFIG)" in config
    assert "find_dependency(freetype" not in config


def test_a_component_without_libraries_is_an_interface_target():
    config = cmake_config(MANIFEST, STORE)

    assert "add_library(freetype::base INTERFACE IMPORTED)" in config


def test_a_consumer_alias_becomes_a_target_that_links_the_real_one():
    config = cmake_config(MANIFEST, STORE, {"Freetype::Freetype": "freetype::freetype"})

    assert "add_library(Freetype::Freetype INTERFACE IMPORTED)" in config
    assert (
        'TARGET Freetype::Freetype PROPERTY INTERFACE_LINK_LIBRARIES "freetype::freetype"' in config
    )


def test_legacy_variables_use_the_name_the_caller_asked_for():
    config = cmake_config(MANIFEST, STORE)

    assert 'set(${CMAKE_FIND_PACKAGE_NAME}_LIBRARIES "freetype::freetype;freetype::base")' in config
    assert (
        'set(${CMAKE_FIND_PACKAGE_NAME}_INCLUDE_DIRS "/store/freetype-1/include/freetype2")'
        in config
    )


def write_stored_package(root: Path, name: str) -> Path:
    package_dir = root / "store" / f"{name}-1"
    (package_dir / "silo").mkdir(parents=True)
    manifest = {"name": name, "version": "1.6", "components": {}}
    (package_dir / "silo" / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package_dir


def test_config_files_are_written_in_lowercase(tmp_path):
    packages = {"libpng": write_stored_package(tmp_path, "libpng")}

    write_dependency_configs(packages, tmp_path / "prefix")

    config_dir = tmp_path / "prefix" / "libpng"
    assert (config_dir / "libpng-config.cmake").is_file()
    assert (config_dir / "libpng-config-version.cmake").is_file()


def test_an_alias_with_another_package_name_makes_the_package_findable_by_it(tmp_path):
    packages = {
        "libpng": write_stored_package(tmp_path, "libpng"),
        "zlib": write_stored_package(tmp_path, "zlib"),
    }

    write_dependency_configs(packages, tmp_path / "prefix", {"PNG::PNG": "libpng::libpng"})

    png_config = tmp_path / "prefix" / "png" / "png-config.cmake"
    assert "add_library(PNG::PNG INTERFACE IMPORTED)" in png_config.read_text(encoding="utf-8")
    zlib_config = tmp_path / "prefix" / "zlib" / "zlib-config.cmake"
    assert "PNG::PNG" not in zlib_config.read_text(encoding="utf-8")
