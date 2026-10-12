import os
from pathlib import Path

import pytest

from silo.enums import Architecture, Compiler
from silo.errors import SiloError
from silo.platform import macos
from silo.platform.macos import MacOSBackend
from silo.tools.cmake.cmake_generator import toolchain_text

TOOLCHAIN = "/Xcode.app/Toolchains/XcodeDefault.xctoolchain/usr/bin"
SDK = "/Xcode.app/SDKs/MacOSX26.5.sdk"


@pytest.fixture
def xcode(monkeypatch):
    """Answer for Xcode, and record the programs silo starts through it."""
    started: list[list[str]] = []
    answers = {
        ("--find", "clang"): f"{TOOLCHAIN}/clang",
        ("--find", "clang++"): f"{TOOLCHAIN}/clang++",
        ("--show-sdk-version",): "26.5",
        ("--show-sdk-path",): SDK,
    }

    def xcrun(*arguments):
        if arguments in answers:
            return answers[arguments]
        started.append([str(argument) for argument in arguments])
        return answers.get(arguments[:2], "")

    monkeypatch.setattr(macos, "_xcrun", xcrun)
    monkeypatch.setattr(macos, "_ask", lambda *command: started.append(list(map(str, command))))
    xcrun.answers, xcrun.started = answers, started
    return xcrun


def test_the_compiler_is_the_one_inside_xcode(xcode, monkeypatch):
    monkeypatch.setattr(macos, "_ask", lambda *command: "21.0.0")

    compiler = MacOSBackend().detect_compiler(Architecture.ARM64)

    assert compiler.kind is Compiler.AppleClang
    assert compiler.executable == Path(TOOLCHAIN) / "clang"
    assert compiler.cxx == Path(TOOLCHAIN) / "clang++"
    assert compiler.generation == "21"
    assert compiler.sdk == "26.5"


def test_a_detected_profile_runs_on_the_first_macos_of_the_sdks_year(xcode, monkeypatch):
    monkeypatch.setattr(macos, "_ask", lambda *command: "21.0.0")

    assert MacOSBackend().detect_compiler(Architecture.X86_64).target == "x86_64-apple-macos26.0"


def test_only_apple_clang_is_detected():
    with pytest.raises(SiloError, match="not gcc"):
        MacOSBackend().detect_compiler(Architecture.ARM64, Compiler.GCC)


def test_a_build_is_told_the_sdk_and_the_oldest_macos_to_run_on(xcode, macos_profile, tmp_path):
    backend = MacOSBackend()

    env = backend.build_env(macos_profile, [Path("/tools/cmake")], tmp_path)

    assert env["SDKROOT"] == SDK
    assert env["MACOSX_DEPLOYMENT_TARGET"] == "15.0"
    assert env["CC"].endswith("clang") and env["CXX"].endswith("clang++")
    assert env["PATH"].split(os.pathsep)[0] == str(Path("/tools/cmake"))
    # A preset built outside silo needs them as well
    assert {"SDKROOT", "MACOSX_DEPLOYMENT_TARGET"} <= set(backend.compiler_environment)


def test_a_target_without_a_macos_version_is_refused(xcode, macos_profile, tmp_path):
    compiler = macos_profile.compiler.model_copy(update={"target": "arm64-apple-darwin27.0.0"})
    profile = macos_profile.model_copy(update={"compiler": compiler})

    with pytest.raises(SiloError, match="oldest version to run on"):
        MacOSBackend().build_env(profile, [], tmp_path)


def test_libraries_are_looked_for_beside_the_file_that_asks(macos_profile):
    toolchain = toolchain_text(macos_profile)

    assert 'set(CMAKE_INSTALL_RPATH "@loader_path;@loader_path/../lib")' in toolchain
    assert "CMAKE_POSITION_INDEPENDENT_CODE" not in toolchain
    assert MacOSBackend().shared_lib_candidates("z")[0] == ("lib/libz.dylib", None)


@pytest.fixture
def installed(tmp_path):
    return tmp_path / "lib" / "libdemo.0.dylib"


def test_a_library_named_by_the_prefix_is_named_by_run_path_and_signed_again(xcode, installed):
    xcode.answers["otool", "-L"] = (
        f"{installed}:\n"
        "\t/silo-prefix-abc/lib/libdemo.0.dylib (compatibility version 1.0.0)\n"
        "\t/silo-prefix-abc/lib/libother.2.dylib (compatibility version 2.0.0)\n"
        "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)"
    )
    xcode.answers["otool", "-D"] = f"{installed}:\n/silo-prefix-abc/lib/libdemo.0.dylib"

    MacOSBackend().use_run_path([installed], "/silo-prefix-abc")

    renamed = ["-id", "@rpath/libdemo.0.dylib"]
    renamed += ["-change", "/silo-prefix-abc/lib/libother.2.dylib", "@rpath/libother.2.dylib"]
    assert xcode.started == [
        ["otool", "-L", str(installed)],
        ["otool", "-D", str(installed)],
        ["install_name_tool", *renamed, str(installed)],
        ["codesign", "--force", "--sign", "-", str(installed)],
    ]


def test_a_library_that_does_not_name_the_prefix_is_left_alone(xcode, installed):
    xcode.answers["otool", "-L"] = f"{installed}:\n\t@rpath/libdemo.0.dylib (compatibility 1)"
    xcode.answers["otool", "-D"] = f"{installed}:\n@rpath/libdemo.0.dylib"

    MacOSBackend().use_run_path([installed], "/silo-prefix-abc")

    assert [command[0] for command in xcode.started] == ["otool", "otool"]
