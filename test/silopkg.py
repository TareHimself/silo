from silo import Options, SiloPackage
from silo.tools.cmake import CMakeGenerator


class TestOptions(Options):
    pass


class TestPackage(SiloPackage[TestOptions]):
    name = "test"
    version = "0.1.0"
    _options_class = TestOptions

    def deps(self):
        self.tool("cmake@4.3")
        print("Options is", self.options)

    def generate(self):
        gen = CMakeGenerator(self)
        gen.add_cache_bool("FOO", True)
        gen.add_cache_bool("BAR", False)
        gen.generate()

    def build(self):
        pass
