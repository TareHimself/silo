import json
from pathlib import Path

import pytest

from silo.errors import SiloError
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
    assert 'PROPERTY IMPORTED_LOCATION "${freetype_ROOT_DIR}/lib/freetype.lib"' in config
    assert (
        'PROPERTY INTERFACE_INCLUDE_DIRECTORIES "${freetype_ROOT_DIR}/include/freetype2"' in config
    )
    assert 'PROPERTY INTERFACE_COMPILE_DEFINITIONS "FT_STATIC"' in config
    assert 'PROPERTY INTERFACE_LINK_LIBRARIES "zlib::zlib;freetype::base;ws2_32"' in config


def test_the_store_path_is_written_once_as_a_variable():
    config = cmake_config(MANIFEST, STORE)

    assert 'set(freetype_ROOT_DIR "/store/freetype-1")' in config
    assert config.count("/store/freetype-1") == 1


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
        'set(${CMAKE_FIND_PACKAGE_NAME}_INCLUDE_DIRS "${freetype_ROOT_DIR}/include/freetype2")'
        in config
    )


def write_stored_package(root: Path, name: str) -> Path:
    package_dir = root / "store" / f"{name}-1"
    (package_dir / "silo").mkdir(parents=True)
    component = {"artifacts": [], "requires": [], "defines": [], "system_libs": []}
    manifest = {"name": name, "version": "1.6", "components": {name: component}}
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


def test_an_alias_for_a_package_that_is_not_a_dependency_is_an_error(tmp_path):
    packages = {"zlib": write_stored_package(tmp_path, "zlib")}

    with pytest.raises(SiloError, match="'libpng' is not a dependency"):
        write_dependency_configs(packages, tmp_path / "prefix", {"PNG::PNG": "libpng::libpng"})


def test_an_alias_for_a_component_that_does_not_exist_is_an_error(tmp_path):
    packages = {"zlib": write_stored_package(tmp_path, "zlib")}

    with pytest.raises(SiloError, match="zlib has no component 'zlibstatic'"):
        write_dependency_configs(packages, tmp_path / "prefix", {"ZLIB::ZLIB": "zlib::zlibstatic"})


def shared_manifest(artifacts: list[dict]) -> dict:
    component = {"artifacts": artifacts, "requires": [], "defines": [], "system_libs": []}
    return {"name": "zlib", "version": "1.3.1", "components": {"zlib": component}}


def test_a_shared_library_is_imported_with_its_import_library():
    manifest = shared_manifest(
        [{"type": "shared_lib", "path": "bin/zlib.dll", "import": "lib/zlib.lib"}]
    )

    config = cmake_config(manifest, Path("/store/zlib-1"))

    assert "add_library(zlib::zlib SHARED IMPORTED)" in config
    assert 'PROPERTY IMPORTED_LOCATION "${zlib_ROOT_DIR}/bin/zlib.dll"' in config
    assert 'PROPERTY IMPORTED_IMPLIB "${zlib_ROOT_DIR}/lib/zlib.lib"' in config


def test_a_shared_library_without_an_import_library_has_only_a_location():
    manifest = shared_manifest([{"type": "shared_lib", "path": "lib/libz.so"}])

    config = cmake_config(manifest, Path("/store/zlib-1"))

    assert 'PROPERTY IMPORTED_LOCATION "${zlib_ROOT_DIR}/lib/libz.so"' in config
    assert "IMPORTED_IMPLIB" not in config


def test_each_extra_shared_library_gets_its_own_target():
    manifest = shared_manifest(
        [
            {"type": "shared_lib", "path": "bin/zlib.dll", "import": "lib/zlib.lib"},
            {"type": "shared_lib", "path": "bin/minizip.dll", "import": "lib/minizip.lib"},
        ]
    )

    config = cmake_config(manifest, Path("/store/zlib-1"))

    assert "add_library(zlib::zlib_minizip SHARED IMPORTED)" in config
    assert 'TARGET zlib::zlib PROPERTY INTERFACE_LINK_LIBRARIES "zlib::zlib_minizip"' in config


def program_manifest() -> dict:
    component = {
        "artifacts": [{"type": "executable", "path": "bin/protoc.exe"}],
        "requires": [],
        "defines": [],
        "system_libs": [],
    }
    library = {
        "artifacts": [
            {"type": "headers", "path": "include"},
            {"type": "static_lib", "path": "lib/protobuf.lib"},
            {"type": "executable", "path": "bin/protobuf.exe"},
            {"type": "executable", "path": "bin/protoc-gen.exe"},
        ],
        "requires": ["zlib::zlib"],
        "defines": [],
        "system_libs": [],
    }
    components = {"protoc": component, "protobuf": library}
    return {"name": "protobuf", "version": "30.0", "components": components}


def test_a_component_of_only_programs_becomes_executable_targets():
    config = cmake_config(program_manifest(), Path("/store/protobuf-1"))

    assert "add_executable(protobuf::protoc IMPORTED)" in config
    assert 'PROPERTY IMPORTED_LOCATION "${protobuf_ROOT_DIR}/bin/protoc.exe"' in config
    assert "add_library(protobuf::protoc " not in config
    assert 'set(${CMAKE_FIND_PACKAGE_NAME}_LIBRARIES "protobuf::protobuf")' in config


def test_a_librarys_programs_get_targets_unless_the_name_is_the_librarys():
    config = cmake_config(program_manifest(), Path("/store/protobuf-1"))

    assert "add_library(protobuf::protobuf STATIC IMPORTED)" in config
    assert "add_executable(protobuf::protoc-gen IMPORTED)" in config
    assert "add_executable(protobuf::protobuf IMPORTED)" not in config


def test_a_tool_offers_its_programs_and_none_of_its_libraries():
    config = cmake_config(program_manifest(), Path("/store/protobuf-1"), programs_only=True)

    assert "add_executable(protobuf::protoc IMPORTED)" in config
    assert "add_executable(protobuf::protobuf IMPORTED)" in config
    assert "add_library" not in config
    assert "find_dependency" not in config
    assert "_LIBRARIES" not in config


def test_a_package_that_is_both_a_tool_and_a_dependency_keeps_its_libraries(tmp_path):
    package_dir = tmp_path / "store" / "protobuf-1"
    (package_dir / "silo").mkdir(parents=True)
    (package_dir / "silo" / "package.json").write_text(json.dumps(program_manifest()))

    write_dependency_configs({}, tmp_path / "tool", tool_packages={"protobuf": package_dir})
    write_dependency_configs(
        {"protobuf": package_dir}, tmp_path / "both", tool_packages={"protobuf": package_dir}
    )

    def config(prefix: str) -> str:
        return (tmp_path / prefix / "protobuf" / "protobuf-config.cmake").read_text()

    assert "add_library" not in config("tool")
    assert "add_library(protobuf::protobuf STATIC IMPORTED)" in config("both")


def test_a_library_keeps_its_name_when_another_components_program_shares_it():
    def component(artifacts: list[dict], requires: list[str]) -> dict:
        return {"artifacts": artifacts, "requires": requires, "defines": [], "system_libs": []}

    components = {
        "msdfgen-core": component([{"type": "static_lib", "path": "lib/msdfgen-core.lib"}], []),
        "msdfgen": component([], ["msdfgen::msdfgen-core"]),
        "msdfgen-run": component([{"type": "executable", "path": "bin/msdfgen.exe"}], []),
    }
    manifest = {"name": "msdfgen", "version": "1.12", "components": components}

    config = cmake_config(manifest, Path("/store/msdfgen-1"))

    assert "add_library(msdfgen::msdfgen INTERFACE IMPORTED)" in config
    assert "add_executable(msdfgen::msdfgen-run IMPORTED)" in config
    assert "add_executable(msdfgen::msdfgen IMPORTED)" not in config
