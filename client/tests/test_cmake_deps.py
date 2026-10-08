from pathlib import Path

from silo.tools.cmake.cmake_deps import cmake_config

MANIFEST = {
    "name": "freetype",
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


def test_config_imports_each_component_by_full_path():
    config = cmake_config(MANIFEST, Path("/store/freetype-1"))

    assert "add_library(freetype::freetype STATIC IMPORTED)" in config
    assert 'PROPERTY IMPORTED_LOCATION "/store/freetype-1/lib/freetype.lib"' in config
    assert 'PROPERTY INTERFACE_INCLUDE_DIRECTORIES "/store/freetype-1/include/freetype2"' in config
    assert 'PROPERTY INTERFACE_COMPILE_DEFINITIONS "FT_STATIC"' in config
    assert 'PROPERTY INTERFACE_LINK_LIBRARIES "zlib::zlib;freetype::base;ws2_32"' in config


def test_config_finds_other_packages_but_not_itself():
    config = cmake_config(MANIFEST, Path("/store/freetype-1"))

    assert "find_dependency(zlib CONFIG)" in config
    assert "find_dependency(freetype" not in config


def test_a_component_without_libraries_is_an_interface_target():
    config = cmake_config(MANIFEST, Path("/store/freetype-1"))

    assert "add_library(freetype::base INTERFACE IMPORTED)" in config
