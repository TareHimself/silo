import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from silo.cache import remove_tree
from silo.errors import ResolutionError, SiloError
from silo.git_snapshot import fetch_commit
from silo.paths import registries_dir

CONFIG_FILE = "silo.config.toml"
RECIPES_DIR = "recipes"
RECIPE_FILE = "silopkg.py"


FULL_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

# What each followed registry points at, asked once per run
_latest: dict[tuple[str, str | None], str] = {}


def _remote_commit(url: str, rev: str | None) -> str | None:
    """The commit a branch or tag of a remote is at now, or None when it cannot be reached."""
    ref = rev or "HEAD"
    result = subprocess.run(
        ["git", "ls-remote", url, ref, f"{ref}^{{}}"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return None
    lines = [line.split("	") for line in result.stdout.splitlines() if line]
    if not lines:
        raise SiloError(f"{url} has no branch or tag named '{ref}'")
    # An annotated tag lists itself and, marked ^{}, the commit it stands for
    peeled = [commit for commit, name in lines if name.endswith("^{}")]
    return (peeled or [lines[0][0]])[0]


@dataclass
class Registry:
    """A folder or git repository holding recipes/<name>/<version>/silopkg.py.

    For a git registry, `rev` is a full commit hash to stay on, or a branch or tag to
    follow. Left out, the default branch is followed.
    """

    name: str
    path: Path | None = None
    git: str | None = None
    rev: str | None = None

    def _commit(self) -> str:
        assert self.git is not None
        if self.rev and FULL_COMMIT.fullmatch(self.rev):
            return self.rev
        key = (self.git, self.rev)
        if key not in _latest:
            remembered = registries_dir() / f"{self.name}.latest"
            commit = _remote_commit(self.git, self.rev)
            if commit is None:
                if not remembered.is_file():
                    raise SiloError(f"The registry '{self.name}' at {self.git} cannot be reached")
                commit = remembered.read_text(encoding="utf-8").strip()
                print(
                    f"registry '{self.name}' cannot be reached, using the copy from {commit[:12]}"
                )
            else:
                remembered.parent.mkdir(parents=True, exist_ok=True)
                remembered.write_text(commit, encoding="utf-8")
            _latest[key] = commit
        return _latest[key]

    @property
    def root(self) -> Path:
        if self.path is not None:
            return self.path
        assert self.git is not None
        commit = self._commit()
        # One folder per commit, so a copy is never changed once it is there
        checkout = registries_dir() / f"{self.name}-{commit[:16]}"
        if not checkout.exists():
            staging = checkout.with_name(f".tmp-{checkout.name}")
            remove_tree(staging)
            fetch_commit(self.git, commit, staging)
            # An empty repository around the files, so a recipe here gets the same hash
            # as the same recipe in a working copy: git's own, which ignores line endings
            # that a checkout converted
            subprocess.run(["git", "init", "--quiet", str(staging)], check=True)
            staging.rename(checkout)
        return checkout

    def versions(self, package: str) -> list[str]:
        folder = self.root / RECIPES_DIR / package
        if not folder.is_dir():
            return []
        return sorted(
            version.name for version in folder.iterdir() if (version / RECIPE_FILE).is_file()
        )


def _parse(config_file: Path) -> list[Registry]:
    config = tomllib.loads(config_file.read_text(encoding="utf-8"))
    registries = []
    for entry in config.get("registry", []):
        name = entry.get("name")
        if not name or ("path" in entry) == ("git" in entry):
            raise SiloError(f"{config_file}: each [[registry]] needs a name and either path or git")
        path = (config_file.parent / entry["path"]).resolve() if "path" in entry else None
        registries.append(Registry(name, path, entry.get("git"), entry.get("rev")))
    return registries


def load_registries(start_dir: Path) -> list[Registry]:
    """The registries of the nearest silo.config.toml, in `start_dir` or a folder above it."""
    start_dir = start_dir.resolve()
    for folder in (start_dir, *start_dir.parents):
        config_file = folder / CONFIG_FILE
        if config_file.is_file():
            return _parse(config_file)
    return []


def _lookup(registries: list[Registry], name: str, version: str) -> Path | list[str] | None:
    """The recipe folder, or the versions the first registry holding the package has."""
    for registry in registries:
        versions = registry.versions(name)
        if version in versions:
            return registry.root / RECIPES_DIR / name / version
        if versions:
            # The first registry that knows the name decides, so a later one cannot shadow it
            return versions
    return None


def find_recipe(registries: list[Registry], name: str, version: str | None, wanted_by: str) -> Path:
    """The folder of the recipe for `name` at exactly `version`."""
    if not version:
        raise ResolutionError(
            f"{wanted_by} depends on '{name}' without a version. Write \"{name}@<version>\"."
        )
    if not registries:
        raise ResolutionError(
            f"{wanted_by} depends on '{name}@{version}', but no {CONFIG_FILE} with a "
            "[[registry]] was found in the project's folder or above it."
        )
    found = _lookup(registries, name, version)
    if isinstance(found, Path):
        return found
    searched = ", ".join(registry.name for registry in registries)
    if found:
        raise ResolutionError(
            f"{wanted_by} depends on '{name}@{version}', but the registry only has "
            f"{name} {', '.join(found)}."
        )
    raise ResolutionError(
        f"{wanted_by} depends on '{name}@{version}', which no registry has (searched {searched})."
    )
