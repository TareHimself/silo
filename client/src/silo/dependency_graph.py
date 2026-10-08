from silo.silo_package import SiloPackage
from semver import Version
from typing import Union, Optional

class ResolvedDependency:
    def __init__(self,name: str,version: Version, options: Optional[dict[str,Union[str,bool,int]]] = None) -> None:
        self.name = name
        self.version = version
        self.options = {} if options is None else options
        self.dependencies: list[ResolvedDependency] = []

    # def add_dependency(self: ResolvedDependency)
def resolve_dependencies(package: SiloPackage):
    pass