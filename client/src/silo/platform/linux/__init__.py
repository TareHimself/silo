from silo.build_profile import Profile
from silo.platform.unix import UnixBackend


class LinuxBackend(UnixBackend):
    name = "linux"

    def hardening_defines(self, profile: Profile) -> list[str]:
        return ["_GLIBCXX_ASSERTIONS"]
