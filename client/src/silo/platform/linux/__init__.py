import shutil
import subprocess
from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture, Compiler
from silo.errors import SiloError
from silo.platform.unix import UnixBackend

# Kind, C compiler, C++ compiler, and the flag that prints the whole version
COMPILERS = (
    (Compiler.GCC, "gcc", "g++", "-dumpfullversion"),
    (Compiler.Clang, "clang", "clang++", "-dumpversion"),
)


# Where a program or library looks for the shared libraries shipped with it: its own
# folder and a lib folder beside it. $ORIGIN is the folder of the file that asks.
RUNTIME_SEARCH = ("$ORIGIN", "$ORIGIN/../lib")


def _ask(compiler: str, flag: str) -> str:
    return subprocess.run(
        [compiler, flag], capture_output=True, text=True, check=True
    ).stdout.strip()


class LinuxBackend(UnixBackend):
    name = "linux"

    def detect_compiler(self, arch: Architecture) -> CompilerProfile:
        for kind, c_name, cxx_name, version_flag in COMPILERS:
            c_compiler, cxx_compiler = shutil.which(c_name), shutil.which(cxx_name)
            if c_compiler and cxx_compiler:
                return CompilerProfile(
                    kind=kind,
                    executable=Path(c_compiler),
                    cxx_executable=Path(cxx_compiler),
                    version=_ask(c_compiler, version_flag),
                    target=_ask(c_compiler, "-dumpmachine"),
                )
        raise SiloError("No gcc or clang was found on PATH together with its C++ compiler")

    def hardening_defines(self, profile: Profile) -> list[str]:
        return ["_GLIBCXX_ASSERTIONS"]

    def cmake_cache_entries(self, profile: Profile) -> dict[str, str]:
        return {
            # A static library has to be usable inside a shared one
            "CMAKE_POSITION_INDEPENDENT_CODE": "ON",
            "CMAKE_INSTALL_RPATH": ";".join(RUNTIME_SEARCH),
        }

    def meson_options(self, profile: Profile) -> dict[str, str | list[str]]:
        search = [f"-Wl,-rpath,{folder}" for folder in RUNTIME_SEARCH]
        return {"c_link_args": search, "cpp_link_args": search}
