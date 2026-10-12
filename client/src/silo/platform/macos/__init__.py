import shutil
import subprocess
from pathlib import Path

from silo.build_profile import CompilerProfile, Profile
from silo.enums import Architecture, Compiler
from silo.errors import SiloError
from silo.platform.unix import UnixBackend

TARGET_ARCHS = {Architecture.ARM64: "arm64", Architecture.X86_64: "x86_64"}
# What comes after the architecture in a target, and before the oldest macOS it runs on
TARGET_SYSTEM = "-apple-macos"


def _ask(*command: str | Path) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise SiloError(f"`{' '.join(map(str, command))}` failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _xcrun(*arguments: str | Path) -> str:
    """Ask Xcode, or the command line tools, about the macOS SDK and the programs for it."""
    xcrun = shutil.which("xcrun")
    if xcrun is None:
        raise SiloError(
            "xcrun was not found. Install Xcode or its command line tools "
            "(`xcode-select --install`)."
        )
    return _ask(xcrun, "--sdk", "macosx", *arguments)


def _named_by_run_path(binary: Path, prefix: str) -> bool:
    """Rename what `binary` says under `prefix`. True if anything was."""
    # The first line is the file itself. A library then gives its own name first.
    listed = _xcrun("otool", "-L", binary).splitlines()[1:]
    names = dict.fromkeys(line.split(" (")[0].strip() for line in listed)
    own = _xcrun("otool", "-D", binary).splitlines()[1:]
    changes: list[str] = []
    for name in names:
        if not name.startswith(prefix):
            continue
        searched = f"@rpath/{Path(name).name}"
        changes += ["-id", searched] if name in own else ["-change", name, searched]
    if changes:
        _xcrun("install_name_tool", *changes, binary)
    return bool(changes)


def deployment_target(profile: Profile) -> str:
    """The oldest macOS a build runs on, which is the end of the profile's target."""
    _, system, version = profile.compiler.target.partition(TARGET_SYSTEM)
    if not system or not version:
        raise SiloError(
            f"The profile's target is '{profile.compiler.target}'. On macOS it ends with the "
            f"oldest version to run on, as in arm64{TARGET_SYSTEM}15.0."
        )
    return version


class MacOSBackend(UnixBackend):
    name = "macos"
    shared_lib_suffix = ".dylib"
    runtime_library_variable = "DYLD_LIBRARY_PATH"
    # Its own folder and a lib folder beside it. @loader_path is the folder of the file
    # that asks.
    runtime_search = ("@loader_path", "@loader_path/../lib")

    @property
    def compiler_environment(self) -> tuple[str, ...]:
        return (*super().compiler_environment, "SDKROOT", "MACOSX_DEPLOYMENT_TARGET")

    def detect_compiler(self, arch: Architecture, kind: Compiler | None = None) -> CompilerProfile:
        """Apple's clang, from the Xcode or command line tools that xcode-select points at."""
        if kind not in (None, Compiler.AppleClang):
            raise SiloError(f"macOS builds with apple_clang, not {kind.value}")
        if arch not in TARGET_ARCHS:
            raise SiloError(f"macOS does not build for {arch.value}")
        c_compiler = Path(_xcrun("--find", "clang"))
        sdk = _xcrun("--show-sdk-version")
        return CompilerProfile(
            kind=Compiler.AppleClang,
            executable=c_compiler,
            cxx_executable=Path(_xcrun("--find", "clang++")),
            version=_ask(c_compiler, "-dumpversion"),
            # Runs on every macOS the SDK's release line covers. Edit it to go further back.
            target=f"{TARGET_ARCHS[arch]}{TARGET_SYSTEM}{sdk.split('.')[0]}.0",
            sdk=sdk,
        )

    def build_env(self, profile: Profile, tool_dirs: list[Path], tmp: Path) -> dict[str, str]:
        env = super().build_env(profile, tool_dirs, tmp)
        # /usr/bin/clang works these out by itself. The compiler inside Xcode, which the
        # profile names, has to be told.
        env["SDKROOT"] = _xcrun("--show-sdk-path")
        env["MACOSX_DEPLOYMENT_TARGET"] = deployment_target(profile)
        return env

    def use_run_path(self, binaries: list[Path], prefix: str) -> None:
        # A library carries the name programs are to ask for it by. Meson makes that the
        # path it is installed to, which is the made-up prefix.
        for binary in binaries:
            if _named_by_run_path(binary, prefix):
                # The edit breaks the signature, and arm64 runs nothing unsigned
                _ask("codesign", "--force", "--sign", "-", binary)

    def hardening_defines(self, profile: Profile) -> list[str]:
        return ["_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST"]
