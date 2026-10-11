import shutil

from silo import Component, Package, SiloPackage
from silo.enums import Platform
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Miniaudio(SiloPackage):
    name = "miniaudio"
    version = "0.11.22"
    languages = ("c",)

    def source(self, src):
        src.git(
            "https://github.com/mackron/miniaudio.git",
            commit="350784a9467a79d0fa65802132668e5afbcf3777",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("MINIAUDIO_BUILD_EXAMPLES", False)
        toolchain.add_cache_bool("MINIAUDIO_BUILD_TESTS", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        # This version has no install step
        library = (
            "miniaudio.lib" if self.profile.settings.os is Platform.Windows else "libminiaudio.a"
        )
        (self.install_dir / "lib").mkdir(parents=True)
        (self.install_dir / "include").mkdir()
        shutil.copy2(self.build_dir / library, self.install_dir / "lib")
        shutil.copy2(self.source_dir / "miniaudio.h", self.install_dir / "include")

    def package(self):
        library = Component("miniaudio", headers=["include"], static_libs=["miniaudio"])
        return Package(components=[library], licenses=["LICENSE"])
