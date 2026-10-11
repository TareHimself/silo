from silo import SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class Webm(SiloPackage):
    """Links webmdx, whose codecs come from plain CMake recipes and from Conan."""

    name = "webm"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("webmdx@1.0.0")
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
