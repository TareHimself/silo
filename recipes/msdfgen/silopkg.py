from silo import Component, Options, Package, SiloPackage
from silo.tools.cmake import CMakeBuild, CMakeDeps, CMakeGenerator


class MsdfgenOptions(Options):
    # Saving PNG files, through libpng
    with_png: bool = True
    # Loading SVG files, through tinyxml2
    with_svg: bool = True
    # The msdfgen command line program
    standalone: bool = True


class Msdfgen(SiloPackage[MsdfgenOptions]):
    name = "msdfgen"
    version = "1.12"
    supports_shared = True

    def source(self, src):
        src.git(
            "https://github.com/Chlumsky/msdfgen.git",
            commit="85e8b3d47b3d1a42e4a5ebda0a24fb1cc2e669e0",
        )

    def patch(self, src):
        # Upstream picks the debug runtime in debug builds. silo uses one runtime everywhere.
        src.replace(
            "CMakeLists.txt",
            'set(MSDFGEN_MSVC_RUNTIME "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")',
            'set(MSDFGEN_MSVC_RUNTIME "MultiThreadedDLL")',
        )

    def deps(self):
        self.dep("../freetype")
        if self.options.with_png:
            self.dep("../libpng")
        if self.options.with_svg:
            self.dep("../tinyxml2")
        self.tool("cmake@4.3")
        self.tool("ninja@1.13")

    def generate(self):
        deps = CMakeDeps(self)
        deps.alias("Freetype::Freetype", "freetype::freetype")
        if self.options.with_png:
            deps.alias("PNG::PNG", "libpng::libpng")
        deps.generate()
        toolchain = CMakeGenerator(self)
        toolchain.add_cache_bool("MSDFGEN_USE_VCPKG", False)
        toolchain.add_cache_bool("MSDFGEN_USE_SKIA", False)
        toolchain.add_cache_bool("MSDFGEN_DYNAMIC_RUNTIME", True)
        toolchain.add_cache_bool("MSDFGEN_INSTALL", True)
        toolchain.add_cache_bool("MSDFGEN_DISABLE_PNG", not self.options.with_png)
        toolchain.add_cache_bool("MSDFGEN_DISABLE_SVG", not self.options.with_svg)
        toolchain.add_cache_bool("MSDFGEN_BUILD_STANDALONE", self.options.standalone)
        toolchain.add_cache_bool("BUILD_SHARED_LIBS", self.options.shared)
        toolchain.generate()

    def build(self):
        cmake = CMakeBuild(self)
        cmake.configure()
        cmake.build()
        cmake.install()

    def package(self):
        # Component names follow the targets of upstream's own config file
        core = Component("msdfgen-core", headers=["include/msdfgen"])
        ext = Component("msdfgen-ext", requires=["msdfgen::msdfgen-core"])
        both = Component("msdfgen", requires=["msdfgen::msdfgen-core", "msdfgen::msdfgen-ext"])
        package = Package(components=[core, ext, both], licenses=["LICENSE.txt"])

        if self.options.shared:
            core.shared_libs.append("msdfgen-core")
            ext.shared_libs.append("msdfgen-ext")
        else:
            core.static_libs.append("msdfgen-core")
            ext.static_libs.append("msdfgen-ext")
            # A static library hands what it links on to whoever links it
            ext.requires.append("freetype")
            if self.options.with_png:
                ext.requires.append("libpng")
            if self.options.with_svg:
                ext.requires.append("tinyxml2")

        if self.options.standalone:
            package.components.append(Component("msdfgen-run", executables=["msdfgen"]))
        return package
