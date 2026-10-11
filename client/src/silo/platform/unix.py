import os
from pathlib import Path

from silo.build_profile import Profile
from silo.platform.base import PlatformBackend

# The compiler needs the assembler, the linker and a shell, which live here
SYSTEM_DIRS = ("/usr/bin", "/bin")


class UnixBackend(PlatformBackend):
    """What Linux and macOS share: file naming and a build environment made from scratch."""

    name: str
    shared_lib_suffix = ".so"
    runtime_library_variable = "LD_LIBRARY_PATH"

    @property
    def compiler_environment(self) -> tuple[str, ...]:
        return ("PATH", "CC", "CXX", self.runtime_library_variable)

    static_lib_suffixes = (".a",)
    executable_suffixes = ("",)

    def build_env(self, profile: Profile, tool_dirs: list[Path], tmp: Path) -> dict[str, str]:
        compiler = profile.compiler
        searched = [*tool_dirs, compiler.executable.parent, compiler.cxx.parent, *SYSTEM_DIRS]
        return {
            "PATH": os.pathsep.join(dict.fromkeys(map(str, searched))),
            "CC": str(compiler.executable),
            "CXX": str(compiler.cxx),
            "TMPDIR": str(tmp),
            "HOME": str(tmp),
            "LANG": "C.UTF-8",
        }

    def static_lib_candidates(self, name: str) -> list[str]:
        return [f"lib/lib{name}.a"]

    def shared_lib_candidates(self, name: str) -> list[tuple[str, str | None]]:
        return [(f"lib/lib{name}{self.shared_lib_suffix}", None)]

    def executable_candidates(self, name: str) -> list[str]:
        return [f"bin/{name}"]
