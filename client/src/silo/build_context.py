from dataclasses import dataclass, field
from pathlib import Path

from silo.build_profile import Profile
from silo.enums import BuildMode


@dataclass(frozen=True)
class BuildContext:
    """Everything silo hands a recipe for one build."""

    profile: Profile
    build_type: BuildMode
    env: dict[str, str]
    source_dir: Path
    build_dir: Path
    stage_dir: Path
    generated_dir: Path
    install_prefix: str
    local_source: bool
    # Store paths of every package this one depends on, directly or not
    dependency_packages: dict[str, Path] = field(default_factory=dict)
    # Alias target -> real target, from this recipe's self.dep(..., aliases=)
    dependency_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def install_dir(self) -> Path:
        return self.stage_dir / self.install_prefix.lstrip("/")
