from silo import SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class Vpx(SiloPackage):
    """Links libvpx, which silo gets from Conan instead of building it."""

    name = "vpx"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("libvpx@1.14.1")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        CMakeDeps(self).generate()
        CMakeGenerator(self).generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
