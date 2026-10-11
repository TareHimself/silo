from dataclasses import dataclass, field, replace

from pydantic import BaseModel

from silo.enums import BuildMode
from silo.options import Options

OptionValue = str | bool | int


def _looks_like_path(spec: str) -> bool:
    return spec.startswith((".", "/", "~")) or "/" in spec or "\\" in spec


class Dependency(BaseModel):
    """What a recipe wrote in self.dep() or self.tool(): "zlib@1.3" or a path such as "../zlib"."""

    name: str | None = None
    version: str | None = None
    path: str | None = None
    options: dict[str, OptionValue] | None = None

    @staticmethod
    def from_str(spec: str, options: dict[str, OptionValue] | None = None) -> "Dependency":
        if _looks_like_path(spec):
            return Dependency(path=spec, options=options)
        name, _, version = spec.partition("@")
        return Dependency(name=name, version=version or None, options=options)


@dataclass(frozen=True)
class Override:
    """A root recipe's decision about a package anywhere in its graph."""

    options: dict[str, OptionValue] = field(default_factory=dict)
    version: str | None = None
    build_type: BuildMode | None = None
    source: str | None = None

    def merged_with(self, later: "Override") -> "Override":
        return replace(
            self,
            options=self.options | later.options,
            version=later.version or self.version,
            build_type=later.build_type or self.build_type,
            source=later.source or self.source,
        )


@dataclass(frozen=True)
class ResolvedDependency:
    """How a dependency was finally resolved, as a recipe sees it in self.dependencies."""

    name: str
    version: str
    options: Options
    build_type: BuildMode
    overridden: bool
    local_source: bool
