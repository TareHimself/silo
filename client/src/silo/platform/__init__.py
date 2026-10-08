import platform as host
from typing import TYPE_CHECKING

from silo.enums import Architecture, Platform

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
