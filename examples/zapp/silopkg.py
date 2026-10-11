from silo import InvalidConfiguration, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator, CMakePresets


class Zapp(SiloPackage):
    name = "zapp"
    version = "0.1.0"

    def source(self, src):
        src.local(".")

    def deps(self):
        # CMakeLists.txt asks for Freetype::Freetype, the name CMake's own find module uses
        self.dep("freetype@2.13.3")
        self.tool("../greetgen")
        self.tool("cmake@4.3")

    def validate(self):
        if self.dependencies["freetype"].options.shared:
            raise InvalidConfiguration("zapp needs a static freetype")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("Freetype::Freetype", "freetype::freetype")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.generate()

        # After `silo sync`: cmake --preset zapp-debug && cmake --build --preset zapp-debug
        name = "debug" if self.is_debug else "release"
        presets = CMakePresets(self, toolchain)
        presets.add(f"zapp-{name}", build_dir=f"build/{name}")
        presets.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()
