import platform as host
from typing import TYPE_CHECKING

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture, Platform
from silo.errors import SiloError

if TYPE_CHECKING:
    from silo.platform.base import PlatformBackend


def get_platform() -> Platform:
    system = host.system()
    match system:
        case "Windows":
            return Platform.Windows
        case "Linux":
            return Platform.Linux
        case "Darwin":
            return Platform.Darwin
        case _:
            raise ValueError(f"Unsupported Platform: {system}")


def get_arch() -> Architecture:
    machine = host.machine().lower()
    match machine:
        case "x86_64" | "amd64":
            return Architecture.X86_64
        case "i386" | "i686":
            return Architecture.X86
        case "arm64" | "aarch64":
            return Architecture.ARM64
        case m if m.startswith("arm"):
            return Architecture.ARM
        case _:
            raise ValueError(f"Unsupported architecture: {machine}")


def backend_for(os: Platform) -> "PlatformBackend":
    match os:
        case Platform.Windows:
            from silo.platform.windows import WindowsBackend

            return WindowsBackend()
        case Platform.Linux:
            from silo.platform.linux import LinuxBackend

            return LinuxBackend()
        case Platform.Darwin:
            from silo.platform.macos import MacOSBackend

            return MacOSBackend()


def detect_compiler_like(wanted: Profile) -> CompilerProfile:
    """This machine's compiler, which has to be the kind and generation `wanted` names."""
    os, compiler = get_platform(), wanted.compiler
    if os is not wanted.settings.os:
        raise SiloError(f"The profile is for {wanted.settings.os.value}, and this is {os.value}")
    found = backend_for(os).detect_compiler(get_arch(), compiler.kind)
    if found.generation != compiler.generation:
        raise SiloError(
            f"The profile names {compiler.kind.value} {compiler.generation} "
            f"(version {compiler.version}), but this machine has {found.generation} "
            f"(version {found.version})"
        )
    return found
