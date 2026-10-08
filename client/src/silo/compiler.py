from typing import Union, TypeAlias, Literal
from abc import ABC, abstractmethod
from silo.platform import get_platform, Platform
from silo.enums import Compiler

class CompilerInfo(ABC):

    @abstractmethod
    def hash(self) -> str:
        pass

class LinuxCompilerInfo(CompilerInfo):
    def __init__(self,compiler: Compiler,version: str,cppstd: int = 20) -> None:
        self.compiler = compiler
        self.version = version
        self.cppstd = cppstd

    def hash(self) -> str:
        raise NotImplementedError()

    @classmethod
    def detect(cls) -> 'LinuxCompilerInfo':
        raise NotImplementedError()
        
class WindowsCompilerInfo(CompilerInfo):
    def __init__(self,compiler: Compiler,version: str,cppstd: int = 20) -> None:
        self.compiler = compiler
        self.version = version
        self.cppstd = cppstd

    @classmethod
    def detect(cls) -> 'LinuxCompilerInfo':
        raise NotImplementedError()

class MacOSCompilerInfo(CompilerInfo):
    def __init__(self,compiler: Compiler,version: str,cppstd: int = 20) -> None:
        self.compiler = compiler
        self.version = version
        self.cppstd = cppstd

    @classmethod
    def detect(cls) -> 'LinuxCompilerInfo':
        raise NotImplementedError()

def detect_compiler() -> CompilerInfo:
    raise NotImplementedError()
        


