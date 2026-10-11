import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from silo.cache import remove_tree
from silo.errors import ResolutionError, SiloError
from silo.git_snapshot import fetch_commit
from silo.paths import registries_dir

CONFIG_FILE = "silo.config.toml"
RECIPES_DIR = "recipes"
RECIPE_FILE = "silopkg.py"
# In a registry folder, in place of the recipe: the repository and commit that hold it
POINTER_FILE = "silopkg.toml"


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

    @property
    def commit(self) -> str:
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
        commit = self.commit
        # One folder per commit, so a copy is never changed once it is there
        checkout = registries_dir() / f"{self.name}-{commit[:16]}"
        if not checkout.exists():
            staging = checkout.with_name(f".tmp-{checkout.name}")
            remove_tree(staging)
            fetch_commit(self.git, commit, staging)
            staging.rename(checkout)
        return checkout

    def versions(self, package: str) -> list[str]:
        folder = self.root / RECIPES_DIR / package
        if not folder.is_dir():
            return []
        return sorted(
            version.name
            for version in folder.iterdir()
            if (version / RECIPE_FILE).is_file() or (version / POINTER_FILE).is_file()
        )


@dataclass
class PinnedPackage:
    """One package the project's config takes from a folder or a git repository."""

    name: str
    path: Path | None = None
    checkout: Registry | None = None
    subdir: str = "."

    @property
    def recipe_dir(self) -> Path:
        root = self.path if self.path is not None else self.checkout.root
        return (root / self.subdir).resolve()


@dataclass
class FetchedFrom:
    """Where the files of a pinned package came from, for a recipe that builds its own folder."""

    url: str
    commit: str
    root: Path


def _source_of(config_file: Path, entry: dict, what: str) -> tuple[Path | None, str | None]:
    if ("path" in entry) == ("git" in entry):
        raise SiloError(f"{config_file}: {what} needs either path or git")
    path = (config_file.parent / entry["path"]).resolve() if "path" in entry else None
    return path, entry.get("git")


@dataclass
class RecipeLookup:
    """Answers a dependency given by name, from the project's silo.config.toml."""

    registries: list[Registry] = field(default_factory=list)
    packages: dict[str, PinnedPackage] = field(default_factory=dict)
    # Packages a recipe gave a git location for, kept to recognise their folders later
    _located: dict[tuple[str, str, str], PinnedPackage] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, start_dir: Path) -> "RecipeLookup":
        """From the nearest silo.config.toml, in `start_dir` or a folder above it."""
        start_dir = start_dir.resolve()
        for folder in (start_dir, *start_dir.parents):
            config_file = folder / CONFIG_FILE
            if config_file.is_file():
                return cls._parse(config_file)
        return cls()

    @classmethod
    def _parse(cls, config_file: Path) -> "RecipeLookup":
        config = tomllib.loads(config_file.read_text(encoding="utf-8"))
        lookup = cls()
        for entry in config.get("registry", []):
            if not entry.get("name"):
                raise SiloError(f"{config_file}: each [[registry]] needs a name")
            path, git = _source_of(config_file, entry, "each [[registry]]")
            lookup.registries.append(Registry(entry["name"], path, git, entry.get("rev")))
        for name, entry in config.get("package", {}).items():
            path, git = _source_of(config_file, entry, f"[package.{name}]")
            checkout = Registry(f"package-{name}", git=git, rev=entry.get("rev")) if git else None
            lookup.packages[name] = PinnedPackage(name, path, checkout, entry.get("subdir", "."))
        return lookup

    def fetched_from(self, recipe_dir: Path) -> FetchedFrom | None:
        """Set for a recipe that came out of a git repository, not out of a registry."""
        for package in (*self.packages.values(), *self._located.values()):
            checkout = package.checkout
            if checkout is not None and package.recipe_dir == recipe_dir.resolve():
                assert checkout.git is not None
                return FetchedFrom(checkout.git, checkout.commit, checkout.root)
        return None

    def _in_registries(self, name: str, version: str) -> Path | list[str] | None:
        """The recipe folder, or the versions the first registry holding the package has."""
        for registry in self.registries:
            versions = registry.versions(name)
            if version in versions:
                return registry.root / RECIPES_DIR / name / version
            if versions:
                # The first registry that knows the name decides, so a later one cannot shadow it
                return versions
        return None

    def _located_by_recipe(self, name: str, git: str, commit: str, subdir: str) -> Path:
        key = (git, commit, subdir)
        if key not in self._located:
            checkout = Registry(f"package-{name}", git=git, rev=commit)
            self._located[key] = PinnedPackage(name, checkout=checkout, subdir=subdir)
        recipe_dir = self._located[key].recipe_dir
        if not (recipe_dir / RECIPE_FILE).is_file():
            raise ResolutionError(f"{git} at {commit[:12]} has no {RECIPE_FILE} in '{subdir}'.")
        return recipe_dir

    def _followed(self, entry: Path, name: str) -> Path:
        """A registry folder's recipe, or the recipe its pointer file leads to."""
        pointer = entry / POINTER_FILE
        if not pointer.is_file():
            return entry
        if (entry / RECIPE_FILE).is_file():
            raise ResolutionError(f"{entry} has both {RECIPE_FILE} and {POINTER_FILE}. Keep one.")
        target = tomllib.loads(pointer.read_text(encoding="utf-8"))
        git, commit = target.get("git"), str(target.get("commit", "")).lower()
        if not git or not FULL_COMMIT.fullmatch(commit):
            raise ResolutionError(f"{pointer} needs git = <repository> and commit = <full hash>.")
        return self._located_by_recipe(name, git, commit, target.get("subdir", "."))

    def find(
        self,
        name: str,
        version: str | None,
        wanted_by: str,
        git: str | None = None,
        commit: str | None = None,
        subdir: str = ".",
    ) -> Path:
        """The folder of the recipe for `name`.

        The project's [package.<name>] entry wins. Then the git location the asking recipe
        gave, if it gave one. Then the registries.
        """
        if name in self.packages:
            recipe_dir = self.packages[name].recipe_dir
            if not (recipe_dir / RECIPE_FILE).is_file():
                raise ResolutionError(
                    f"[package.{name}] in {CONFIG_FILE} points at {recipe_dir}, which has no "
                    f"{RECIPE_FILE}."
                )
            return recipe_dir
        if git and commit:
            return self._located_by_recipe(name, git, commit, subdir)
        if not version:
            raise ResolutionError(
                f"{wanted_by} depends on '{name}' without a version. Write \"{name}@<version>\"."
            )
        if not self.registries:
            raise ResolutionError(
                f"{wanted_by} depends on '{name}@{version}', but no {CONFIG_FILE} with a "
                f"[[registry]] or a [package.{name}] was found in the project's folder or above it."
            )
        found = self._in_registries(name, version)
        if isinstance(found, Path):
            return self._followed(found, name)
        if found:
            raise ResolutionError(
                f"{wanted_by} depends on '{name}@{version}', but the registry only has "
                f"{name} {', '.join(found)}."
            )
        searched = ", ".join(registry.name for registry in self.registries)
        raise ResolutionError(
            f"{wanted_by} depends on '{name}@{version}', which no registry has "
            f"(searched {searched})."
        )
