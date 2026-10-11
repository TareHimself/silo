from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class VulkanLoader(SiloPackage):
    name = "vulkan-loader"
    version = "1.3.296"
    languages = ("c",)

    def source(self, src):
        src.git(
            "https://github.com/KhronosGroup/Vulkan-Loader.git",
            commit="7aeb5e4324957b6f60dac5c8cedb955df4fecbfb",
        )

    def patch(self, src):
        # Upstream asks for the headers by a package name silo does not write
        src.replace(
            "CMakeLists.txt",
            "find_package(VulkanHeaders CONFIG QUIET)",
            "find_package(Vulkan CONFIG REQUIRED)",
        )

    def deps(self):
        self.dep("../vulkan-headers")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("Vulkan::Headers", "vulkan-headers::vulkan-headers")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("BUILD_TESTS", False)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        # Drivers find the loader by this file name, so it is always a shared library
        loader = Component("vulkan-loader", shared_libs=["vulkan-1"], requires=["vulkan-headers"])
        return Package(components=[loader], licenses=["LICENSE.txt"])
