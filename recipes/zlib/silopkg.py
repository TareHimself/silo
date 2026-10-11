from silo import Component, Options, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class ZlibOptions(Options):
    pass


class Zlib(SiloPackage[ZlibOptions]):
    name = "zlib"
    version = "1.3.1"
    languages = ("c",)
    supports_shared = True

    def source(self, src):
        src.fetch(
            "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz",
            sha256="9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("ZLIB_BUILD_EXAMPLES", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        # zlib always builds both kinds, so the option only picks which one is packaged
        if self.options.shared:
            library = Component("zlib", headers=["include"], shared_libs=["zlib"])
        else:
            library = Component("zlib", headers=["include"], static_libs=["zlibstatic"])
        return Package(components=[library], licenses=["LICENSE"])
