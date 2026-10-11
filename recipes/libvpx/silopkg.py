from silo import Component, Package, SiloPackage
from silo.enums import Platform
from silo.tools.conan import ConanInstall


class Libvpx(SiloPackage):
    name = "libvpx"
    version = "1.14.1"
    languages = ("c",)

    def source(self, src):
        src.empty()

    def deps(self):
        self.tool("conan@2")

    def build(self):
        # Upstream builds with configure and make, which silo cannot drive
        ConanInstall(self).install(
            "libvpx/1.14.1#18d555b919f7824741bf2f9422f09a36",
            # Conan's recipe does not know newer MSVC. A C library from 194 links fine.
            settings={"compiler.version": "194"},
        )

    def package(self):
        # On Windows upstream names the library after the runtime it links: md is the DLL one
        library = "vpxmd" if self.profile.settings.os is Platform.Windows else "vpx"
        component = Component(
            "libvpx", headers=["include"], static_libs=[library], content=["licenses"]
        )
        return Package(components=[component])
