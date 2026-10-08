from silo import InvalidConfiguration, SiloPackage
from silo.tools.cmake import CMakeBuild


class Zapp(SiloPackage):
    name = "zapp"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        self.dep("../../recipes/zlib")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def validate(self):
        if self.dependencies["zlib"].options.shared:
            raise InvalidConfiguration("zapp needs a static zlib")

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
