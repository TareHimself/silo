import pytest

from silo import platform
from silo.enums import Architecture, Compiler, Platform
from silo.errors import SiloError
from silo.platform import linux
from silo.platform.linux import LinuxBackend
from silo.platform.windows import WindowsBackend


@pytest.fixture
def installed(monkeypatch):
    """Pretend these compilers are on PATH, and nothing else."""

    def install(*names: str) -> None:
        found = lambda name: f"/usr/bin/{name}" if name in names else None  # noqa: E731
        monkeypatch.setattr(linux.shutil, "which", found)
        monkeypatch.setattr(linux, "_ask", lambda compiler, flag: "1.2.3")

    return install


def test_gcc_is_taken_when_both_are_installed(installed):
    installed("gcc", "g++", "clang", "clang++")

    assert LinuxBackend().detect_compiler(Architecture.X86_64).kind is Compiler.GCC


def test_clang_can_be_asked_for(installed):
    installed("gcc", "g++", "clang", "clang++")

    compiler = LinuxBackend().detect_compiler(Architecture.X86_64, Compiler.Clang)

    assert compiler.kind is Compiler.Clang
    assert compiler.cxx.name == "clang++"


def test_asking_for_a_compiler_that_is_not_installed_names_it(installed):
    installed("gcc", "g++")

    with pytest.raises(SiloError, match="No clang was found"):
        LinuxBackend().detect_compiler(Architecture.X86_64, Compiler.Clang)


def test_a_compiler_the_system_does_not_build_with_is_refused():
    with pytest.raises(SiloError, match="not msvc"):
        LinuxBackend().detect_compiler(Architecture.X86_64, Compiler.MSVC)
    with pytest.raises(SiloError, match="not gcc"):
        WindowsBackend().detect_compiler(Architecture.X86_64, Compiler.GCC)


@pytest.fixture
def on_linux(monkeypatch, installed):
    monkeypatch.setattr(platform, "get_platform", lambda: Platform.Linux)
    monkeypatch.setattr(platform, "get_arch", lambda: Architecture.X86_64)
    installed("gcc", "g++", "clang", "clang++")


def versioned(profile, **changes):
    return profile.model_copy(update={"compiler": profile.compiler.model_copy(update=changes)})


def test_a_matching_profile_decides_the_kind_of_compiler(on_linux, linux_profile):
    wanted = versioned(linux_profile, kind=Compiler.Clang, version="1")

    assert platform.detect_compiler_like(wanted).kind is Compiler.Clang


def test_a_patch_release_apart_still_matches(on_linux, linux_profile):
    wanted = versioned(linux_profile, version="1.9")

    assert platform.detect_compiler_like(wanted).version == "1.2.3"


def test_another_major_version_does_not_match(on_linux, linux_profile):
    with pytest.raises(SiloError, match=r"names gcc 13 .* this machine has 1 "):
        platform.detect_compiler_like(linux_profile)


def test_a_profile_for_another_system_does_not_match(on_linux, windows_profile):
    with pytest.raises(SiloError, match="for windows, and this is linux"):
        platform.detect_compiler_like(windows_profile)
