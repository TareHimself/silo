from typing import Generic, Optional, Union
from typing_extensions import TypeVar
from silo_common.dependency import Dependency
from pathlib import Path
from pydantic import BaseModel
from silo.enums import BuildMode

class Options(BaseModel):
    shared: bool = False
    build_mode: BuildMode = BuildMode.Release


T = TypeVar("T", bound=Options, default=Options)


class SiloPackage(Generic[T]):
    _options_class: type[T] = Options  # type: ignore

    def __init__(self, path: Path, options: T) -> None:
        self._dependencies: list[Dependency] = []
        self._tools: list[Dependency] = []
        self._path = path
        self._source = path.read_text()
        self.options: T = options

    @classmethod
    def build_options(cls, raw: list[str]) -> T:
        data = dict(pair.split("=", 1) for pair in raw)
        return cls._options_class(**data) # type: ignore
    
    def source(self,source_path: Path):
        pass

    def dep(self,name: str,options: Optional[dict[str,Union[str,bool,int]]] = None):
        self._dependencies.append(Dependency.from_str(name,options))

    def tool(self,name: str,options: Optional[dict[str,Union[str,bool,int]]] = None):
        self._tools.append(Dependency.from_str(name,options))

    def deps(self):
        pass

    def generate(self):
        pass

    def build(self):
        pass

    def package(self):
        pass



