
import platform
from silo.enums import Platform, Architecture




def get_platform() -> Platform:
    system = platform.system()
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
    machine = platform.machine().lower()
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