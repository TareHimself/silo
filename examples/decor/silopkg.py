from silo import InvalidConfiguration, SiloPackage
from silo.enums import Platform
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class Decor(SiloPackage):
    """Links libdecor, whose whole dependency chain silo builds with Meson. Linux only."""

    name = "decor"
    version = "0.1.0"
    languages = ("c",)

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("libdecor@0.2.2")
        self.dep("wayland@1.22.0")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def validate(self):
        if self.profile.settings.os is not Platform.Linux:
            raise InvalidConfiguration("decor needs Wayland, so it only builds on Linux")

    def generate(self):
        CMakeDeps(self).generate()
        CMakeGenerator(self).generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
