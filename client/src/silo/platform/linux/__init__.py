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


def _ask(compiler: str, flag: str) -> str:
    return subprocess.run(
        [compiler, flag], capture_output=True, text=True, check=True
    ).stdout.strip()


class LinuxBackend(UnixBackend):
    name = "linux"
    position_independent = True
    # Its own folder and a lib folder beside it. $ORIGIN is the folder of the file that asks.
    runtime_search = ("$ORIGIN", "$ORIGIN/../lib")

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
