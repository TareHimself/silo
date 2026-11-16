import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, ConfigDict

from silo.enums import Architecture, Compiler, Platform, RuntimeLinkage
from silo.errors import SiloError

# What a settings-only file may not change, since the compiler it is given was found for them
FIXED_BY_THE_COMPILER = ("os", "arch")


class Settings(BaseModel):
    # A misspelled key in a settings-only file would otherwise change nothing, silently
    model_config = ConfigDict(extra="forbid")

    os: Platform
    arch: Architecture
    cppstd: int = 20
    libcxx: str | None = None
    runtime: RuntimeLinkage = RuntimeLinkage.Dynamic


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

    model_config = ConfigDict(extra="forbid")

    settings: Settings
    compiler: CompilerProfile

    @classmethod
    def load(cls, path: Path, base: Path | None = None) -> "Profile":
        """A file without a compiler holds settings only, which go over the profile at `base`."""
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if "compiler" in data or base is None:
            return cls.model_validate(data)
        if not base.exists():
            raise SiloError(
                f"{path} names no compiler, so its settings go over the profile at {base}, "
                "which is not there. Run `silo profile detect` first."
            )
        below = cls.load(base)
        merged = below.model_dump(mode="json", exclude_none=True) | data
        merged["settings"] = below.settings.model_dump(mode="json", exclude_none=True) | data.get(
            "settings", {}
        )
        profile = cls.model_validate(merged)
        for key in FIXED_BY_THE_COMPILER:
            wanted, found = getattr(profile.settings, key), getattr(below.settings, key)
            if wanted is not found:
                raise SiloError(
                    f"{path} is for {wanted.value}, and the profile at {base} is for {found.value}"
                )
        return profile

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=True)
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
