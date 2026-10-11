from silo import Component, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class VkBootstrap(SiloPackage):
    name = "vk-bootstrap"
    version = "1.3.296"

    def source(self, src):
        src.git(
            "https://github.com/charles-lunarg/vk-bootstrap.git",
            commit="f85a1f1e28a724dfd7404ceb953b2c5903a6f1c6",
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
        toolchain.add_cache_bool("VK_BOOTSTRAP_TEST", False)
        toolchain.add_cache_bool("VK_BOOTSTRAP_INSTALL", True)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        library = Component(
            "vk-bootstrap",
            headers=["include"],
            static_libs=["vk-bootstrap"],
            requires=["vulkan-headers"],
        )
        return Package(components=[library], licenses=["LICENSE.txt"])
