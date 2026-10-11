from abc import ABC, abstractmethod
from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture


class PlatformBackend(ABC):
    """Everything that differs per operating system. Core code never branches on the OS."""

    static_lib_suffixes: tuple[str, ...]
    # The variables of build_env() a compiler needs, for tools that run it outside silo
    compiler_environment: tuple[str, ...]
    # The variable the system searches for shared libraries when a program starts
    runtime_library_variable: str
    executable_suffixes: tuple[str, ...]

    @abstractmethod
    def detect_compiler(self, arch: Architecture) -> CompilerProfile: ...

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

    def cmake_cache_entries(self, profile: Profile) -> dict[str, str]:
        return {}

    def cmake_initial_cache(self, profile: Profile) -> dict[str, str]:
        """Entries CMake must know before it reads the project's first line."""
        return {}

    def meson_options(self, profile: Profile) -> dict[str, str | list[str]]:
        """Built-in Meson options every build on this system needs."""
        return {}
