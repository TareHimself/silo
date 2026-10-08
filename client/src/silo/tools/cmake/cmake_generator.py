from typing import Generic, TypeVar
from silo.silo_package import Options, SiloPackage

T = TypeVar("T", bound=Options)


class CMakeGenerator(Generic[T]):
    def __init__(self, package: SiloPackage[T]) -> None:
        self.package: SiloPackage[T] = package


    def add_cache_string(self, key: str, value: str):
        pass

    def add_cache_bool(self,key: str,value: bool):
        pass

    def generate(self):
        pass