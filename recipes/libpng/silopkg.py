from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class Libpng(SiloPackage):
    name = "libpng"
    version = "1.6.59"
    languages = ("c",)

    def source(self, src):
        src.git(
            "https://github.com/pnggroup/libpng.git",
            commit="cd952f49f95bb27154ae77dbb103032d95f6e580",
        )

    def deps(self):
        self.dep("../zlib")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("ZLIB::ZLIB", "zlib::zlib")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("PNG_SHARED", False)
        toolchain.add_cache_bool("PNG_TESTS", False)
        toolchain.add_cache_bool("PNG_TOOLS", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[
                Component(
                    "libpng",
                    headers=["include"],
                    static_libs=["libpng16_static"],
                    requires=["zlib"],
                )
            ],
            licenses=["LICENSE"],
        )
