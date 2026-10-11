from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Tinyxml2(SiloPackage):
    name = "tinyxml2"
    version = "11.0.0"

    def source(self, src):
        src.git(
            "https://github.com/leethomason/tinyxml2.git",
            commit="9148bdf719e997d1f474be6bcc7943881046dba1",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("BUILD_TESTING", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[Component("tinyxml2", headers=["include"], static_libs=["tinyxml2"])],
            licenses=["LICENSE.txt"],
        )
