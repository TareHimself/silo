from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Libyuv(SiloPackage):
    name = "libyuv"
    version = "1974"

    def source(self, src):
        src.git(
            "https://chromium.googlesource.com/libyuv/libyuv",
            commit="eeb06a6451ba2e21f8ff272c7b42fc62b9faecc5",
        )

    def patch(self, src):
        # The shared library's import library would overwrite the static library
        src.replace(
            "CMakeLists.txt",
            'OUTPUT_NAME "${ly_lib_name}"',
            'OUTPUT_NAME "${ly_lib_name}_shared"',
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("LIBYUV_DISABLE_JPEG", True)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[Component("libyuv", headers=["include"], static_libs=["yuv"])],
            licenses=["LICENSE"],
        )
