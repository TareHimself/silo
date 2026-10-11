from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture
from silo.platform.base import PlatformBackend


class UnixBackend(PlatformBackend):
    """File naming shared by Linux and macOS. Detection and build envs are not written yet."""

    name: str
    shared_lib_suffix = ".so"
    runtime_library_variable = "LD_LIBRARY_PATH"

    @property
    def compiler_environment(self) -> tuple[str, ...]:
        return ("PATH", "CC", "CXX", self.runtime_library_variable)

    static_lib_suffixes = (".a",)
    executable_suffixes = ("",)

    def detect_compiler(self, arch: Architecture) -> CompilerProfile:
        raise NotImplementedError(f"Compiler detection is not implemented for {self.name}")

    def build_env(self, profile: Profile, tool_dirs: list[Path], tmp: Path) -> dict[str, str]:
        raise NotImplementedError(f"Build environments are not implemented for {self.name}")

    def static_lib_candidates(self, name: str) -> list[str]:
        return [f"lib/lib{name}.a"]

    def shared_lib_candidates(self, name: str) -> list[tuple[str, str | None]]:
        return [(f"lib/lib{name}{self.shared_lib_suffix}", None)]

    def executable_candidates(self, name: str) -> list[str]:
        return [f"bin/{name}"]
