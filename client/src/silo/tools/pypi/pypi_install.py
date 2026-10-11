import shutil
import sys
from collections.abc import Sequence
from typing import Any

from silo.enums import Platform
from silo.errors import SiloError
from silo.package import Component, Package
from silo.silo_package import SiloPackage


class PyPIInstall:
    """Takes a program that PyPI ships ready-made, such as CMake, as this build's result."""

    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package

    def install(self, requirement: str) -> None:
        """Install `requirement`, such as "cmake==4.3.4", into the install folder."""
        uv = shutil.which("uv")
        if uv is None:
            raise SiloError(f"{self.package.name} is installed from PyPI, which needs uv on PATH")
        target = self.package.install_dir
        install = [uv, "pip", "install", "--quiet", "--python", sys.executable]
        self.package.run([*install, "--target", target, requirement])

    def packaged(self, programs: Sequence[str] | None = None, bin_dir: str = "bin") -> Package:
        """Everything that was installed, with the programs in `bin_dir` as its executables.

        Left out, `programs` is the one named like the package.
        """
        windows = self.package.profile.settings.os is Platform.Windows
        suffix = ".exe" if windows else ""
        names = programs or [self.package.name]
        component = Component(
            self.package.name,
            executables=[f"{bin_dir}/{name}{suffix}" for name in names],
            content=["."],
        )
        return Package(components=[component])
