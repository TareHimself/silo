from silo import SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator, CMakePresets


class Sdf(SiloPackage):
    """Links msdfgen, which brings freetype, libpng, tinyxml2 and zlib with it."""

    name = "sdf"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        # sdf saves PNG files and never reads SVG, so tinyxml2 drops out of the graph
        self.dep("msdfgen@1.12", options={"with_svg": False})
        # Also as a tool, which puts the msdfgen program on the build PATH
        self.tool("msdfgen@1.12")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        CMakeDeps(self).generate()
        toolchain = CMakeGenerator(self)
        toolchain.generate()

        name = "debug" if self.is_debug else "release"
        presets = CMakePresets(self, toolchain)
        presets.add(f"sdf-{name}", build_dir=f"build/{name}")
        presets.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
