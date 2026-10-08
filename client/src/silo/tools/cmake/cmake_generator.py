from silo.options import Options
from silo.silo_package import SiloPackage


class CMakeGenerator[T: Options]:
    def __init__(self, package: SiloPackage[T]) -> None:
        self.package: SiloPackage[T] = package

    def add_cache_string(self, key: str, value: str):
        pass

    def add_cache_bool(self, key: str, value: bool):
        pass

    def generate(self):
        pass
