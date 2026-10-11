import json

import pytest

from silo.build_context import BuildContext
from silo.enums import BuildMode
from silo.tools.cmake import CMakeGenerator, CMakePresets
from silo.tools.cmake.cmake_presets import write_presets_index


@pytest.fixture
def demo_package(load_demo_recipe, windows_profile, tmp_path):
    def make(build_type: BuildMode = BuildMode.Debug, in_project: bool = True):
        package = load_demo_recipe("")
        project_generated = tmp_path / ".silo"
        package._context = BuildContext(
            profile=windows_profile,
            build_type=build_type,
            env={"PATH": "C:/tools", "INCLUDE": "C:/sdk/include", "TEMP": "C:/tmp"},
            source_dir=tmp_path / "src",
            build_dir=tmp_path / "build",
            stage_dir=tmp_path / "stage",
            generated_dir=project_generated / build_type.value,
            install_prefix="/silo-prefix-abc",
            local_source=True,
            project_generated_dir=project_generated if in_project else None,
        )
        return package

    return make


def presets_for(package) -> CMakePresets:
    return CMakePresets(package, CMakeGenerator(package))


def test_the_hidden_preset_holds_what_silo_knows(demo_package):
    base = presets_for(demo_package()).document()["configurePresets"][0]

    assert base["name"] == "silo-debug"
    assert base["hidden"] is True
    assert base["generator"] == "Ninja"
    assert base["toolchainFile"] == "${fileDir}/silo-toolchain.cmake"


def test_the_hidden_preset_carries_only_the_compilers_environment(demo_package):
    base = presets_for(demo_package()).document()["configurePresets"][0]

    assert base["environment"] == {"PATH": "C:/tools", "INCLUDE": "C:/sdk/include"}


def test_an_added_preset_inherits_it_with_its_own_name_and_folder(demo_package):
    presets = presets_for(demo_package())
    presets.add("Rin-Debug", build_dir="build-debug")

    document = presets.document()

    preset = document["configurePresets"][1]
    assert preset["name"] == "Rin-Debug"
    assert preset["inherits"] == "silo-debug"
    assert preset["binaryDir"] == "${sourceDir}/build-debug"
    assert preset["cacheVariables"] == {"CMAKE_BUILD_TYPE": "Debug"}
    linked = {"name": "Rin-Debug", "configurePreset": "Rin-Debug"}
    assert document["buildPresets"] == [linked]
    assert document["testPresets"] == [linked]


def test_a_preset_takes_cache_entries_and_anything_else_cmake_accepts(demo_package):
    presets = presets_for(demo_package())
    preset = presets.add("Rin-Debug")
    preset.cache["RIN_BUILD_TEST_MAIN"] = True
    preset.environment["RIN_LOG"] = "verbose"
    preset.configure["displayName"] = "Rin (debug)"
    preset.build["jobs"] = 8
    preset.test["output"] = {"outputOnFailure": True}

    document = presets.document()

    configure = document["configurePresets"][1]
    assert configure["cacheVariables"]["RIN_BUILD_TEST_MAIN"] == "ON"
    assert configure["environment"] == {"RIN_LOG": "verbose"}
    assert configure["displayName"] == "Rin (debug)"
    assert configure["binaryDir"] == "${sourceDir}/build/Rin-Debug"
    assert document["buildPresets"][0]["jobs"] == 8
    assert document["testPresets"][0]["output"] == {"outputOnFailure": True}


def test_the_build_type_follows_the_configuration_being_generated(demo_package):
    presets = presets_for(demo_package(BuildMode.Release))
    presets.add("Rin-Release")

    document = presets.document()

    assert document["configurePresets"][0]["name"] == "silo-release"
    assert document["configurePresets"][1]["cacheVariables"] == {"CMAKE_BUILD_TYPE": "Release"}


def test_generating_both_configurations_lists_both_in_the_index(demo_package, tmp_path):
    for build_type in (BuildMode.Debug, BuildMode.Release):
        presets_for(demo_package(build_type)).generate()

    index = json.loads((tmp_path / ".silo" / "CMakePresets.json").read_text(encoding="utf-8"))
    assert index["include"] == ["debug/CMakePresets.json", "release/CMakePresets.json"]


def test_the_index_lists_only_configurations_that_have_presets(tmp_path):
    (tmp_path / "debug").mkdir()
    (tmp_path / "debug" / "CMakePresets.json").write_text("{}")
    (tmp_path / "release").mkdir()

    index = json.loads(write_presets_index(tmp_path).read_text(encoding="utf-8"))

    assert index["include"] == ["debug/CMakePresets.json"]


def test_a_store_build_writes_no_index(demo_package, tmp_path):
    presets_for(demo_package(in_project=False)).generate()

    assert (tmp_path / ".silo" / "debug" / "CMakePresets.json").is_file()
    assert not (tmp_path / ".silo" / "CMakePresets.json").exists()


def test_the_toolchain_generators_cache_entries_reach_every_preset(demo_package):
    package = demo_package()
    toolchain = CMakeGenerator(package)
    toolchain.add_cache_bool("MSDFGEN_USE_SKIA", False)
    toolchain.generate()
    presets = CMakePresets(package, toolchain)
    presets.add("Rin-Debug").cache["MSDFGEN_USE_SKIA"] = True

    base, preset = presets.document()["configurePresets"]

    assert base["cacheVariables"] == {
        "CMAKE_POLICY_DEFAULT_CMP0091": "NEW",
        "MSDFGEN_USE_SKIA": "OFF",
    }
    assert preset["cacheVariables"]["MSDFGEN_USE_SKIA"] == "ON"


def test_the_hidden_preset_carries_what_the_platform_needs_early(demo_package):
    package = demo_package()
    CMakeGenerator(package).generate()

    base = presets_for(package).document()["configurePresets"][0]
    assert base["cacheVariables"] == {"CMAKE_POLICY_DEFAULT_CMP0091": "NEW"}
