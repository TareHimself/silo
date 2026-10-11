import shutil
import sys
from pathlib import Path
from typing import Any

from silo.errors import SiloError
from silo.silo_package import SiloPackage
from silo.tools.meson.meson_generator import NATIVE_FILE
from silo.tools.pkgconfig.pkg_config_deps import PC_DIR


class MesonBuild:
    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package

    def _meson(self, *arguments: str | Path) -> None:
        context = self.package.context
        launcher = shutil.which("meson", path=context.env["PATH"])
        if launcher is None:
            raise SiloError(
                f'{self.package.name} uses MesonBuild, so its deps() needs self.tool("meson@1")'
            )
        environment = {
            # The launcher in the tool's bin folder cannot find Meson's modules by itself
            "PYTHONPATH": str(Path(launcher).parent.parent),
            # Only what PkgConfigDeps wrote is visible, never the machine's own packages
            "PKG_CONFIG_LIBDIR": str(context.generated_dir / PC_DIR),
        }
        self.package.run(
            [sys.executable, "-m", "mesonbuild.mesonmain", *arguments], env=environment
        )

    def configure(self) -> None:
        context = self.package.context
        native_file = context.generated_dir / NATIVE_FILE
        if not native_file.is_file():
            raise SiloError(
                f"{self.package.name} has no Meson native file. "
                "Call MesonGenerator(self).generate() in the recipe's generate()."
            )
        self._meson("setup", context.build_dir, context.source_dir, "--native-file", native_file)

    def build(self) -> None:
        self._meson("compile", "-C", self.package.build_dir)

    def install(self) -> None:
        # The prefix is a sentinel, so the destdir is what puts the files in the stage dir
        context = self.package.context
        self._meson(
            "install", "-C", context.build_dir, "--no-rebuild", "--destdir", context.stage_dir
        )
