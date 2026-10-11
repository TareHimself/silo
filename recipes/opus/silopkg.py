from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Opus(SiloPackage):
    name = "opus"
    version = "1.5.2"
    languages = ("c",)

    def source(self, src):
        src.git(
            "https://github.com/xiph/opus.git",
            commit="ddbe48383984d56acd9e1ab6a090c54ca6b735a6",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("OPUS_BUILD_SHARED_LIBRARY", False)
        toolchain.add_cache_bool("OPUS_BUILD_PROGRAMS", False)
        toolchain.add_cache_bool("OPUS_BUILD_TESTING", False)
        toolchain.add_cache_bool("OPUS_STATIC_RUNTIME", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[
                Component("opus", headers=["include", "include/opus"], static_libs=["opus"])
            ],
            licenses=["COPYING"],
        )
