from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture
from silo.errors import SiloError
from silo.platform.unix import UnixBackend


class MacOSBackend(UnixBackend):
    name = "macos"
    shared_lib_suffix = ".dylib"
    runtime_library_variable = "DYLD_LIBRARY_PATH"

    def detect_compiler(self, arch: Architecture) -> CompilerProfile:
        raise SiloError("Compiler detection is not written for macOS yet")

    def hardening_defines(self, profile: Profile) -> list[str]:
        return ["_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST"]
