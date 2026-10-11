from silo import Component, InvalidConfiguration, Options, Package, SiloPackage
from silo.enums import Platform
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class RwinOptions(Options):
    shared: bool = True


class Rwin(SiloPackage[RwinOptions]):
    name = "rwin"
    version = "1.0.1"
    supports_shared = True

    def source(self, src):
        src.git(
            "https://github.com/TareHimself/rwin.git",
            commit="eee112f96e0f066929d8244953e99874f7385e8f",
        )

    def patch(self, src):
        # All fixed upstream after this commit, which builds its macOS sources everywhere
        src.replace("CMakeLists.txt", "LANGUAGES C CXX OBJCXX", "LANGUAGES C CXX")
        src.replace("CMakeLists.txt", ' "${CMAKE_CURRENT_LIST_DIR}/lib/*.mm"', "")
        src.replace(
            "lib/rwin/windows/WindowsWindowManager.cpp",
            "WindowInfo{windowId, hwnd, false,dropTarget}",
            "WindowInfo{.id = windowId, .hwnd = hwnd, .dropTarget = dropTarget}",
        )

    def deps(self):
        self.dep("../vulkan-loader")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def validate(self):
        if self.profile.settings.os is not Platform.Windows:
            raise InvalidConfiguration("The rwin recipe has no Wayland or macOS dependencies yet")
        # Its headers always import from a DLL on Windows
        if not self.options.shared:
            raise InvalidConfiguration("rwin can only be a shared library on Windows")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("Vulkan::Vulkan", "vulkan-loader::vulkan-loader")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_string("RWIN_VERSION", self.version)
        toolchain.add_cache_bool("BUILD_SHARED_LIBS", self.options.shared)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        library = Component(
            "rwin", headers=["include"], shared_libs=["rwin"], requires=["vulkan-loader"]
        )
        return Package(components=[library], licenses=["LICENSE"])
