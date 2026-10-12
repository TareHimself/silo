import shutil
import sys
from pathlib import Path
from typing import Any

from silo.build_profile import Profile
from silo.enums import Architecture, BuildMode, Compiler, Platform, RuntimeLibrary
from silo.errors import SiloError
from silo.paths import conan_dir
from silo.platform import backend_for
from silo.silo_package import SiloPackage

PROFILE_FILE = "conan-profile"
DEPLOYER = "direct_deploy"

CONAN_OS = {Platform.Windows: "Windows", Platform.Linux: "Linux", Platform.Darwin: "Macos"}
CONAN_ARCH = {
    Architecture.X86_64: "x86_64",
    Architecture.X86: "x86",
    Architecture.ARM64: "armv8",
    Architecture.ARM: "armv7",
}

# compiler.runtime and compiler.runtime_type
CONAN_RUNTIME = {RuntimeLibrary.DynamicRelease: ("dynamic", "Release")}

# The GNU C++ library with the C++11 ABI, which gcc and clang both use on Linux
GNU_LIBCXX = "libstdc++11"
# Conan's name for a compiler, and the C++ library it links unless the profile says
CONAN_COMPILER = {
    Compiler.GCC: ("gcc", GNU_LIBCXX),
    Compiler.Clang: ("clang", GNU_LIBCXX),
    Compiler.AppleClang: ("apple-clang", "libc++"),
}

OptionValue = str | bool | int


def _compiler_settings(profile: Profile) -> dict[str, str]:
    compiler = profile.compiler
    if compiler.kind is Compiler.MSVC:
        backend = backend_for(profile.settings.os)
        runtime, runtime_type = CONAN_RUNTIME[backend.runtime_library(profile)]
        return {
            "compiler": "msvc",
            "compiler.version": compiler.generation,
            "compiler.runtime": runtime,
            "compiler.runtime_type": runtime_type,
        }
    name, libcxx = CONAN_COMPILER[compiler.kind]
    return {
        "compiler": name,
        "compiler.version": compiler.generation,
        "compiler.libcxx": profile.settings.libcxx or libcxx,
    }


def conan_settings(profile: Profile, build_type: BuildMode) -> dict[str, str]:
    """silo's profile in Conan's words, with the release runtime silo uses for every build."""
    return {
        "os": CONAN_OS[profile.settings.os],
        "arch": CONAN_ARCH[profile.settings.arch],
        "build_type": "Debug" if build_type is BuildMode.Debug else "Release",
        **_compiler_settings(profile),
        "compiler.cppstd": str(profile.settings.cppstd),
    }


def profile_text(settings: dict[str, str]) -> str:
    return "\n".join(["[settings]", *(f"{key}={value}" for key, value in settings.items())]) + "\n"


class ConanInstall:
    """Gets one package from Conan and lays it out as this build's install folder.

    For libraries whose own build silo cannot drive yet. Conan keeps its files in silo's
    cache, never in the user's own Conan folder.
    """

    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package

    def _conan_root(self) -> Path:
        launcher = shutil.which("conan", path=self.package.env["PATH"])
        if launcher is None:
            raise SiloError(
                f'{self.package.name} uses ConanInstall, so its deps() needs self.tool("conan@2")'
            )
        return Path(launcher).parent.parent

    def install(
        self,
        reference: str,
        options: dict[str, OptionValue] | None = None,
        settings: dict[str, str] | None = None,
    ) -> None:
        """Install `reference`, such as "libvpx/1.14.1", building it if Conan has no binary.

        `options` are the Conan package's own, or a dependency's when written the way Conan
        does, such as "libcurl/*:with_ssl". `settings` replaces entries of the profile silo
        would write, for a package that refuses the real ones.
        """
        context = self.package.context
        name = reference.split("/")[0]
        context.generated_dir.mkdir(parents=True, exist_ok=True)
        profile = context.generated_dir / PROFILE_FILE
        merged = conan_settings(context.profile, context.build_type) | (settings or {})
        profile.write_text(profile_text(merged), encoding="utf-8")

        deploy_dir = context.build_dir / "conan"
        command: list[str | Path] = [
            sys.executable,
            "-m",
            "conans.conan",
            "install",
            f"--requires={reference}",
            "--profile:all",
            profile,
            "--build=missing",
            f"--deployer={DEPLOYER}",
            f"--deployer-folder={deploy_dir}",
            "--output-folder",
            context.build_dir / "conan-out",
        ]
        for key, value in (options or {}).items():
            scoped = key if ":" in key else f"{name}/*:{key}"
            command += ["--options", f"{scoped}={value}"]

        # The launcher in the tool's bin folder cannot find Conan's modules by itself
        environment = {"CONAN_HOME": str(conan_dir()), "PYTHONPATH": str(self._conan_root())}
        self.package.run(command, env=environment)

        deployed = deploy_dir / DEPLOYER / name
        if not deployed.is_dir():
            raise SiloError(f"Conan did not deploy '{name}' to {deployed}")
        shutil.copytree(deployed, context.install_dir, dirs_exist_ok=True)
