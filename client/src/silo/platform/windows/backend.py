import os
import shutil
from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture, Compiler
from silo.platform.base import PlatformBackend
from silo.platform.windows.msvc import capture_vcvars, find_visual_studio

MSVC_TARGETS = {
    Architecture.X86_64: "x86_64-pc-windows-msvc",
    Architecture.X86: "i686-pc-windows-msvc",
    Architecture.ARM64: "aarch64-pc-windows-msvc",
}

# Always the release runtime (/MD), so debug and release objects link together as on other platforms
MSVC_RUNTIME = "MultiThreadedDLL"

# vcvars puts Visual Studio's own cmake and ninja on PATH, which would satisfy an undeclared tool
VS_BUNDLED_TOOL_DIRS = (r"\CommonExtensions\Microsoft\CMake",)


def _is_vs_bundled_tool_dir(path: str) -> bool:
    return any(bundled.lower() in path.lower() for bundled in VS_BUNDLED_TOOL_DIRS)


class WindowsBackend(PlatformBackend):
    static_lib_suffixes = (".lib", ".a")
    executable_suffixes = (".exe",)

    def detect_compiler(self, arch: Architecture) -> CompilerProfile:
        install_path = find_visual_studio()
        env = capture_vcvars(install_path, arch)
        cl = shutil.which("cl.exe", path=env["PATH"])
        if cl is None:
            raise RuntimeError("cl.exe is not on the PATH set up by vcvarsall.bat")
        return CompilerProfile(
            kind=Compiler.MSVC,
            executable=Path(cl),
            version=env["VCToolsVersion"],
            target=MSVC_TARGETS[arch],
            install_path=install_path,
            sdk=env.get("WindowsSDKVersion", "").rstrip("\\") or None,
        )

    def build_env(self, profile: Profile, tool_dirs: list[Path], tmp: Path) -> dict[str, str]:
        compiler = profile.compiler
        if compiler.kind is not Compiler.MSVC or compiler.install_path is None:
            raise NotImplementedError(
                f"Windows builds with {compiler.kind.value} are not implemented"
            )

        env = capture_vcvars(compiler.install_path, profile.settings.arch)
        compiler_dirs = [
            path
            for path in env["PATH"].split(os.pathsep)
            if path and not _is_vs_bundled_tool_dir(path)
        ]
        env["PATH"] = os.pathsep.join([*map(str, tool_dirs), *compiler_dirs])
        env["TEMP"] = env["TMP"] = str(tmp)
        env["CC"] = env["CXX"] = str(compiler.executable)
        return env

    def static_lib_candidates(self, name: str) -> list[str]:
        return [f"lib/{name}.lib", f"lib/lib{name}.a", f"lib/{name}d.lib"]

    def executable_candidates(self, name: str) -> list[str]:
        return [f"bin/{name}.exe"]

    def hardening_defines(self, profile: Profile) -> list[str]:
        if profile.compiler.kind is not Compiler.MSVC:
            return []
        return ["_MSVC_STL_HARDENING=1"]

    def cmake_cache_entries(self, profile: Profile) -> dict[str, str]:
        if profile.compiler.kind is not Compiler.MSVC:
            return {}
        return {"CMAKE_MSVC_RUNTIME_LIBRARY": MSVC_RUNTIME}
