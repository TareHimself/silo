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
    # Set by `silo sync`: the project's .silo folder, which holds one folder per build type
    project_generated_dir: Path | None = None
    # Store paths of every package this one depends on, directly or not
    dependency_packages: dict[str, Path] = field(default_factory=dict)
    # Store paths of the packages this one declared with self.tool()
    tool_packages: dict[str, Path] = field(default_factory=dict)
    # Where the output of the recipe's commands goes instead of the terminal
    log: Path | None = None

    @property
    def install_dir(self) -> Path:
        return self.stage_dir / self.install_prefix.lstrip("/")
