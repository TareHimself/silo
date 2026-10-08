from pathlib import Path

import pytest

from silo.build_context import BuildContext
from silo.enums import BuildMode
from silo.tools.cmake import CMakeBuild


@pytest.fixture
def configure_arguments(load_demo_recipe, windows_profile, tmp_path, monkeypatch):
    def configure(build_type: BuildMode, extra_class_body: str = "") -> list[str]:
        package = load_demo_recipe(extra_class_body)
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
        commands = []
        monkeypatch.setattr(package, "run", lambda args, **_: commands.append(args))
        CMakeBuild(package).configure()
        return [str(argument) for argument in commands[0]]

    return configure


def test_debug_cxx_build_turns_on_stl_hardening(configure_arguments):
    arguments = configure_arguments(BuildMode.Debug)
    assert "-DCMAKE_CXX_FLAGS_INIT=-D_MSVC_STL_HARDENING=1" in arguments


def test_release_build_has_no_hardening(configure_arguments):
    arguments = configure_arguments(BuildMode.Release)
    assert not any("HARDENING" in argument for argument in arguments)


def test_c_only_recipe_has_no_cxx_flags(configure_arguments):
    arguments = configure_arguments(BuildMode.Debug, '    languages = ("c",)\n')
    assert not any("CMAKE_CXX_FLAGS_INIT" in argument for argument in arguments)


def test_windows_always_uses_the_release_runtime(configure_arguments):
    for build_type in (BuildMode.Debug, BuildMode.Release):
        arguments = configure_arguments(build_type)
        assert "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL" in arguments


def test_install_prefix_is_the_sentinel(configure_arguments):
    arguments = configure_arguments(BuildMode.Release)
    assert "-DCMAKE_INSTALL_PREFIX=/silo-prefix-abc" in arguments
    assert Path(arguments[2]).name == "src"
