from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Libwebm(SiloPackage):
    name = "libwebm"
    version = "1.0.0.31"

    def source(self, src):
        src.git(
            "https://github.com/webmproject/libwebm.git",
            commit="6745fd29e0245fc584b0bb9f65018ea2366fe7fb",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_string("CMAKE_POLICY_VERSION_MINIMUM", "3.5")
        # Upstream defaults to the static runtime. silo uses the DLL one everywhere.
        toolchain.add_cache_string("MSVC_RUNTIME", "dll")
        toolchain.add_cache_bool("ENABLE_WEBMTS", False)
        toolchain.add_cache_bool("ENABLE_WEBMINFO", False)
        toolchain.add_cache_bool("ENABLE_TESTS", False)
        toolchain.add_cache_bool("ENABLE_SAMPLE_PROGRAMS", False)
        toolchain.add_cache_bool("ENABLE_WEBM_PARSER", True)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        return Package(
            components=[Component("webm", headers=["include"], static_libs=["webm"])],
            licenses=["LICENSE.TXT"],
        )
