from silo import SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeGenerator


class Greetgen(SiloPackage):
    """A code generator. zapp runs it during its build with self.tool("../greetgen")."""

    name = "greetgen"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.tool("cmake@4.3")

    def generate(self):
        CMakeGenerator(self).generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
