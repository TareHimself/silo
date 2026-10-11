from silo.build_profile import Profile
from silo.platform.unix import UnixBackend


class MacOSBackend(UnixBackend):
    name = "macos"
    shared_lib_suffix = ".dylib"
    runtime_library_variable = "DYLD_LIBRARY_PATH"

    def hardening_defines(self, profile: Profile) -> list[str]:
        return ["_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST"]
