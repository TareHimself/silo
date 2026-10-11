import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel

from silo.enums import Architecture, Compiler, Platform


class Settings(BaseModel):
    os: Platform
    arch: Architecture
    cppstd: int = 20
    libcxx: str | None = None


class CompilerProfile(BaseModel):
    kind: Compiler
    executable: Path
    # The C++ compiler, where it is a different program from the C one
    cxx_executable: Path | None = None
    version: str
    target: str
    install_path: Path | None = None
    sdk: str | None = None

    @property
    def cxx(self) -> Path:
        return self.cxx_executable or self.executable


class Profile(BaseModel):
    """What a machine can build with. Project decisions (options, build type) live elsewhere."""

    settings: Settings
    compiler: CompilerProfile

    @classmethod
    def load(cls, path: Path) -> "Profile":
        return cls.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=True)
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
