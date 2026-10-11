from silo import Component, InvalidConfiguration, Options, Package, SiloPackage
from silo.enums import Platform
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator

CODECS = ["libvpx", "dav1d", "opus"]


class WebmdxOptions(Options):
    shared: bool = True


class Webmdx(SiloPackage[WebmdxOptions]):
    name = "webmdx"
    version = "1.0.0"
    supports_shared = True

    def source(self, src):
        src.git(
            "https://github.com/TareHimself/webmdx.git",
            commit="ee5da08a378b0e8818c520c6fa883ebed44b7a2f",
        )

    def deps(self):
        self.dep("../libwebm")
        self.dep("../libyuv")
        for codec in CODECS:
            self.dep(f"../{codec}")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def validate(self):
        # Its headers always import from a DLL on Windows
        if self.profile.settings.os is Platform.Windows and not self.options.shared:
            raise InvalidConfiguration("webmdx can only be a shared library on Windows")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("webm::webm", "libwebm::webm")
        deps.alias("Opus::opus", "opus::opus")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("BUILD_SHARED_LIBS", self.options.shared)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        library = Component("webmdx", headers=["include"])
        if self.options.shared:
            library.shared_libs.append("webmdx")
        else:
            library.static_libs.append("webmdx")
            library.requires += ["libwebm::webm", "libyuv", *CODECS]
        return Package(components=[library], licenses=["LICENSE"])
