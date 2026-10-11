import re
from dataclasses import dataclass, field, replace

from pydantic import BaseModel

from silo.enums import BuildMode
from silo.errors import SiloError
from silo.options import Options

OptionValue = str | bool | int

FULL_COMMIT = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")


def _looks_like_path(spec: str) -> bool:
    return spec.startswith((".", "/", "~")) or "/" in spec or "\\" in spec


class Dependency(BaseModel):
    """What a recipe wrote in self.dep() or self.tool(): "zlib@1.3" or a path such as "../zlib"."""

    name: str | None = None
    version: str | None = None
    path: str | None = None
    options: dict[str, OptionValue] | None = None
    # Where the recipe is when no registry has it: a repository, a full commit hash and
    # the folder in it that holds silopkg.py
    git: str | None = None
    commit: str | None = None
    subdir: str = "."
    # For a tool: whoever uses the declaring package as a tool can run this one too
    transitive: bool = False

    @staticmethod
    def from_str(
        spec: str,
        options: dict[str, OptionValue] | None = None,
        git: str | None = None,
        commit: str | None = None,
        subdir: str = ".",
        transitive: bool = False,
    ) -> "Dependency":
        if _looks_like_path(spec):
            if git:
                raise SiloError(f"'{spec}' is a path, so it cannot also come from {git}")
            return Dependency(path=spec, options=options, transitive=transitive)
        name, _, version = spec.partition("@")
        if git and not (commit and FULL_COMMIT.fullmatch(commit)):
            raise SiloError(
                f"'{name}' from {git} needs commit=<full hash>. A branch or tag can move, and "
                "following one is for the project's own silo.config.toml."
            )
        if commit and not git:
            raise SiloError(f"'{name}' has a commit but no git repository to find it in")
        return Dependency(
            name=name,
            version=version or None,
            options=options,
            git=git,
            commit=commit.lower() if commit else None,
            subdir=subdir,
            transitive=transitive,
        )


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
