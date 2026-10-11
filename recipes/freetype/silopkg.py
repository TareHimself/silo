from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class Freetype(SiloPackage):
    name = "freetype"
    version = "2.13.3"
    languages = ("c",)

    def source(self, src):
        src.fetch(
            "https://download.savannah.gnu.org/releases/freetype/freetype-2.13.3.tar.xz",
            sha256="0550350666d427c74daeb85d5ac7bb353acba5f76956395995311a9c6f063289",
        )

    def deps(self):
        self.dep("../zlib")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        CMakeDeps(self).generate()
        CMakeGenerator(self).generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure(
            FT_REQUIRE_ZLIB=True,
            FT_DISABLE_BZIP2=True,
            FT_DISABLE_PNG=True,
            FT_DISABLE_HARFBUZZ=True,
            FT_DISABLE_BROTLI=True,
        )
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[
                Component(
                    "freetype",
                    headers=["include/freetype2"],
                    static_libs=["freetype"],
                    requires=["zlib"],
                )
            ],
            licenses=["LICENSE.TXT", "docs/FTL.TXT"],
        )
