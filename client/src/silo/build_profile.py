import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel

from silo.enums import Architecture, Compiler, Platform


class Settings(BaseModel):
    os: Platform
    arch: Architecture
    cppstd: int = 17
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

    @property
    def generation(self) -> str:
        """The part of the version that decides which binaries can be mixed.

        For gcc and clang it is the major version. Every MSVC since 2015 is toolset 14, so
        there it is Microsoft's compiler number: toolsets 14.40 to 14.49 are 194.
        """
        major, _, rest = self.version.partition(".")
        if self.kind is not Compiler.MSVC:
            return major
        minor = int(rest.split(".")[0] or 0)
        return str(int(major) * 10 + 50 + minor // 10)


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
