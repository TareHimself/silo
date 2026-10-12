from abc import ABC, abstractmethod
from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture, Compiler, RuntimeLibrary


class PlatformBackend(ABC):
    """Everything that differs per operating system. Core code never branches on the OS."""

    static_lib_suffixes: tuple[str, ...]
    # The variables of build_env() a compiler needs, for tools that run it outside silo
    compiler_environment: tuple[str, ...]
    # The variable the system searches for shared libraries when a program starts
    runtime_library_variable: str
    executable_suffixes: tuple[str, ...]
    # Whether a static library must be built so it can go inside a shared one
    position_independent: bool = False
    # Folders a program or library searches for the shared libraries shipped with it
    runtime_search: tuple[str, ...] = ()

    @abstractmethod
    def detect_compiler(self, arch: Architecture, kind: Compiler | None = None) -> CompilerProfile:
        """The compiler this machine builds with. `kind` asks for one of several."""

    @abstractmethod
    def build_env(self, profile: Profile, tool_dirs: list[Path], tmp: Path) -> dict[str, str]:
        """The full environment for a build. The search path is always under the key PATH."""

    @abstractmethod
    def static_lib_candidates(self, name: str) -> list[str]:
        """Install-relative paths a library called `name` could have, most likely first."""

    @abstractmethod
    def shared_lib_candidates(self, name: str) -> list[tuple[str, str | None]]:
        """Like static_lib_candidates, each paired with its import library where there is one."""

    @abstractmethod
    def executable_candidates(self, name: str) -> list[str]:
        """Install-relative paths an executable called `name` could have."""

    @abstractmethod
    def hardening_defines(self, profile: Profile) -> list[str]:
        """Preprocessor defines that turn on the C++ standard library's hardened mode."""

    def cxx_flags(self, profile: Profile) -> list[str]:
        """Flags every C++ compile gets, so the compiler reads the language as others do."""
        return []

    def runtime_library(self, profile: Profile) -> RuntimeLibrary | None:
        """The runtime every build links, or None where the compiler has only one."""
        return None
