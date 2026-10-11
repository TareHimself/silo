import sys
from pathlib import Path

import pytest

from silo.build_context import BuildContext
from silo.enums import BuildMode
from silo.errors import CommandFailed, SiloError
from silo.tools.cmake import CMakeBuild, CMakeGenerator


@pytest.fixture
def demo_package(load_demo_recipe, windows_profile, tmp_path, monkeypatch):
    def make(build_type: BuildMode = BuildMode.Release):
        package = load_demo_recipe("")
        package._context = BuildContext(
            profile=windows_profile,
            build_type=build_type,
            env={},
            source_dir=tmp_path / "src",
            build_dir=tmp_path / "build",
            stage_dir=tmp_path / "stage",
            generated_dir=tmp_path / "generated",
            install_prefix="/silo-prefix-abc",
            local_source=False,
        )
        package.commands = []
        monkeypatch.setattr(package, "run", lambda args, **_: package.commands.append(args))
        return package

    return make


def configure_arguments(package) -> list[str]:
    CMakeBuild(package).configure()
    return [str(argument) for argument in package.commands[0]]


def test_toolchain_sets_the_compiler_and_the_cpp_standard(demo_package, windows_profile):
    toolchain = CMakeGenerator(demo_package()).generate().read_text(encoding="utf-8")

    compiler = windows_profile.compiler.executable.as_posix()
    assert f'set(CMAKE_C_COMPILER "{compiler}")' in toolchain
    assert f'set(CMAKE_CXX_COMPILER "{compiler}")' in toolchain
    assert 'set(CMAKE_CXX_STANDARD "20")' in toolchain


def test_toolchain_hardens_the_stl_in_debug_builds_only(demo_package):
    toolchain = CMakeGenerator(demo_package()).generate().read_text(encoding="utf-8")

    assert 'set(CMAKE_CXX_FLAGS_DEBUG_INIT "-D_MSVC_STL_HARDENING=1")' in toolchain
    assert toolchain.count("HARDENING") == 1


def test_toolchain_always_uses_the_release_runtime_on_windows(demo_package):
    toolchain = CMakeGenerator(demo_package()).generate().read_text(encoding="utf-8")

    assert 'set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")' in toolchain


def test_toolchain_finds_dependency_configs_next_to_itself(demo_package):
    toolchain = CMakeGenerator(demo_package()).generate().read_text(encoding="utf-8")

    assert 'list(PREPEND CMAKE_PREFIX_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake")' in toolchain
    assert 'set(CMAKE_FIND_PACKAGE_PREFER_CONFIG "ON")' in toolchain


def test_the_machines_folders_are_searched_only_when_a_recipe_asks(demo_package):
    strict = CMakeGenerator(demo_package())
    lenient = CMakeGenerator(demo_package())
    lenient.allow_system_packages()

    switch = 'set(CMAKE_FIND_USE_CMAKE_SYSTEM_PATH "OFF")'
    assert switch in strict.generate().read_text(encoding="utf-8")
    assert switch not in lenient.generate().read_text(encoding="utf-8")


def test_cache_entries_go_into_a_file_cmake_reads_before_the_project(demo_package):
    package = demo_package()
    generator = CMakeGenerator(package)
    generator.add_cache_bool("ZLIB_BUILD_EXAMPLES", False)
    generator.add_cache_string("FT_FLAVOUR", "small")

    toolchain = generator.generate()

    cache_file = toolchain.with_name("silo-cache.cmake")
    cache = cache_file.read_text(encoding="utf-8")
    assert 'set(ZLIB_BUILD_EXAMPLES "OFF" CACHE BOOL "" FORCE)' in cache
    assert 'set(FT_FLAVOUR "small" CACHE STRING "" FORCE)' in cache
    assert "ZLIB_BUILD_EXAMPLES" not in toolchain.read_text(encoding="utf-8")
    assert generator.cache == {
        "CMAKE_POLICY_DEFAULT_CMP0091": "NEW",
        "ZLIB_BUILD_EXAMPLES": "OFF",
        "FT_FLAVOUR": "small",
    }
    arguments = configure_arguments(package)
    assert arguments[arguments.index("-C") + 1] == str(cache_file)


def test_an_old_cmake_project_is_told_to_honour_the_runtime_on_windows(demo_package):
    package = demo_package()
    toolchain = CMakeGenerator(package).generate()

    cache = toolchain.with_name("silo-cache.cmake").read_text(encoding="utf-8")
    assert 'set(CMAKE_POLICY_DEFAULT_CMP0091 "NEW" CACHE STRING "" FORCE)' in cache


@pytest.mark.parametrize(
    ("build_type", "cmake_name"), [(BuildMode.Debug, "Debug"), (BuildMode.Release, "Release")]
)
def test_configure_uses_the_toolchain_and_the_build_type(demo_package, build_type, cmake_name):
    package = demo_package(build_type)
    toolchain = CMakeGenerator(package).generate()

    arguments = configure_arguments(package)

    assert arguments[arguments.index("--toolchain") + 1] == str(toolchain)
    assert f"-DCMAKE_BUILD_TYPE={cmake_name}" in arguments


def test_install_prefix_is_the_sentinel(demo_package):
    package = demo_package()
    CMakeGenerator(package).generate()

    arguments = configure_arguments(package)

    assert "-DCMAKE_INSTALL_PREFIX=/silo-prefix-abc" in arguments
    assert Path(arguments[2]).name == "src"


def test_configure_without_a_toolchain_says_how_to_get_one(demo_package):
    with pytest.raises(SiloError, match=r"CMakeGenerator\(self\)\.generate\(\)"):
        CMakeBuild(demo_package()).configure()


def test_a_failing_command_is_reported_without_a_traceback(
    load_demo_recipe, windows_profile, tmp_path
):
    package = load_demo_recipe("")
    package._context = BuildContext(
        profile=windows_profile,
        build_type=BuildMode.Release,
        env={"PATH": str(Path(sys.executable).parent)},
        source_dir=tmp_path,
        build_dir=tmp_path,
        stage_dir=tmp_path,
        generated_dir=tmp_path,
        install_prefix="/silo-prefix-abc",
        local_source=False,
    )

    with pytest.raises(SiloError, match="demo: the command failed with exit code 3"):
        package.run([Path(sys.executable).name, "-c", "raise SystemExit(3)"])
    with pytest.raises(SiloError, match="'nosuchtool' is not a declared tool"):
        package.run(["nosuchtool"])


def test_with_a_log_the_output_of_commands_goes_there(load_demo_recipe, windows_profile, tmp_path):
    package = load_demo_recipe("")
    package._context = BuildContext(
        profile=windows_profile,
        build_type=BuildMode.Release,
        env={"PATH": str(Path(sys.executable).parent)},
        source_dir=tmp_path,
        build_dir=tmp_path,
        stage_dir=tmp_path,
        generated_dir=tmp_path,
        install_prefix="/silo-prefix-abc",
        local_source=False,
        log=tmp_path / "demo.log",
    )
    python = Path(sys.executable).name

    package.run([python, "-c", "print('compiling')"])
    with pytest.raises(CommandFailed, match="Its output is in") as failure:
        package.run([python, "-c", "print('broken'); raise SystemExit(3)"])

    log = (tmp_path / "demo.log").read_text(encoding="utf-8")
    assert "compiling" in log and "broken" in log
    assert failure.value.exit_code == 3
