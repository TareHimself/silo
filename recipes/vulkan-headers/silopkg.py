from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class VulkanHeaders(SiloPackage):
    name = "vulkan-headers"
    version = "1.3.296"
    header_only = True

    def source(self, src):
        src.git(
            "https://github.com/KhronosGroup/Vulkan-Headers.git",
            commit="29f979ee5aa58b7b005f805ea8df7a855c39ff37",
        )

    def deps(self):
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("VULKAN_HEADERS_ENABLE_TESTS", False)
        toolchain.add_cache_bool("VULKAN_HEADERS_ENABLE_MODULE", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        headers = Component("vulkan-headers", headers=["include"])
        return Package(components=[headers], licenses=["LICENSE.md"])
