from typing import Any

from silo.enums import BuildMode
from silo.errors import SiloError
from silo.silo_package import SiloPackage
from silo.tools.cmake.cmake_generator import CACHE_FILE, TOOLCHAIN_FILE

CacheValue = str | bool | int


def _cache_argument(key: str, value: CacheValue) -> str:
    if isinstance(value, bool):
        value = "ON" if value else "OFF"
    return f"-D{key}={value}"


class CMakeBuild:
    def __init__(self, package: SiloPackage[Any]) -> None:
        self.package = package

    def configure(self, **cache: CacheValue) -> None:
        context = self.package.context
        toolchain = context.generated_dir / TOOLCHAIN_FILE
        if not toolchain.is_file():
            raise SiloError(
                f"{self.package.name} has no CMake toolchain file. "
                "Call CMakeGenerator(self).generate() in the recipe's generate()."
            )
        entries: dict[str, CacheValue] = {
            "CMAKE_BUILD_TYPE": "Debug" if context.build_type is BuildMode.Debug else "Release",
            "CMAKE_INSTALL_PREFIX": context.install_prefix,
            **cache,
        }
        cache_file = context.generated_dir / CACHE_FILE
        self.package.run(
            ["cmake", "-S", context.source_dir, "-B", context.build_dir, "-G", "Ninja"]
            + ["--toolchain", toolchain]
            + (["-C", cache_file] if cache_file.is_file() else [])
            + [_cache_argument(key, value) for key, value in entries.items()]
        )

    def build(self) -> None:
        self.package.run(["cmake", "--build", self.package.build_dir])

    def install(self) -> None:
        # The prefix is a sentinel, so DESTDIR is what puts the files in the stage dir
        self.package.run(
            ["cmake", "--install", self.package.build_dir],
            env={"DESTDIR": str(self.package.context.stage_dir)},
        )
