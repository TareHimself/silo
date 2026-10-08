from silo import InvalidConfiguration, SiloPackage
from silo.tools.cmake import CMakeBuild


class Zapp(SiloPackage):
    name = "zapp"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        # CMakeLists.txt asks for Freetype::Freetype, the name CMake's own find module uses
        self.dep("../../recipes/freetype", aliases={"Freetype::Freetype": "freetype::freetype"})
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def validate(self):
        if self.dependencies["freetype"].options.shared:
            raise InvalidConfiguration("zapp needs a static freetype")

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
