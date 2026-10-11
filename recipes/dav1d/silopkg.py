from silo import Component, Package, SiloPackage
from silo.tools.conan import ConanInstall


class Dav1d(SiloPackage):
    name = "dav1d"
    version = "1.4.3"
    languages = ("c",)

    def source(self, src):
        src.empty()

    def deps(self):
        self.tool("conan@2")

    def build(self):
        ConanInstall(self).install(
            "dav1d/1.4.3#5e2459e132c77183bd16d23d12fd8f4a",
            # Conan Center has no binaries for newer MSVC. A C library from 194 links fine.
            settings={"compiler.version": "194"},
        )

    def package(self):
        component = Component(
            "dav1d", headers=["include"], static_libs=["dav1d"], content=["licenses"]
        )
        return Package(components=[component])
