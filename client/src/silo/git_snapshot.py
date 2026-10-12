"""Hash and copy a folder's current contents through git, without touching the user's repo.

A snapshot covers tracked and untracked files and respects .gitignore. It never needs a commit:
silo keeps its own index file and writes new objects into its own cache.
"""

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import xxhash

from silo.errors import SiloError
from silo.paths import git_sources_dir, snapshots_dir
from silo.retry import retrying

# Windows stops at 260 characters in a path unless git is told otherwise, and a store in a
# deep folder plus a source with long file names goes past that. Ignored elsewhere.
GIT = ("git", "-c", "core.longpaths=true")


@dataclass(frozen=True)
class Repo:
    top: Path
    git_dir: Path
    objects: Path


def _rev_parse(directory: Path, *flags: str) -> list[str] | None:
    result = subprocess.run(
        ["git", "rev-parse", *flags],
        cwd=directory,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    return result.stdout.splitlines() if result.returncode == 0 else None


def find_repo(directory: Path) -> Repo | None:
    lines = _rev_parse(directory, "--show-toplevel", "--absolute-git-dir", "--git-path", "objects")
    if lines is None:
        return None
    top, git_dir, objects = lines
    return Repo(Path(top).resolve(), Path(git_dir), (directory / objects).resolve())


def _require_repo(directory: Path) -> Repo:
    repo = find_repo(directory)
    if repo is None:
        raise SiloError(f"Local source must be inside a git repository: {directory}")
    return repo


def _silo_git_dir(directory: Path) -> Path:
    key = xxhash.xxh128(str(directory).encode()).hexdigest()[:16]
    return snapshots_dir() / key


def _git(repo: Repo, work_tree: Path, index_file: Path, *args: str) -> str:
    """Run git against the repo's history, but with silo's own index, objects and work tree."""
    objects = _silo_git_dir(repo.top) / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    env = os.environ | {
        "GIT_DIR": str(repo.git_dir),
        "GIT_WORK_TREE": str(work_tree),
        "GIT_INDEX_FILE": str(index_file),
        "GIT_OBJECT_DIRECTORY": str(objects),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(repo.objects),
    }
    result = subprocess.run(
        [*GIT, *args], cwd=work_tree, env=env, capture_output=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise SiloError(f"git {' '.join(args)} failed in {work_tree}:\n{result.stderr.strip()}")
    return result.stdout.strip()


def _snapshot_index(repo: Repo, directory: Path) -> Path:
    """silo's index for this folder, started from the repo's own so unchanged files hash once."""
    index_file = _silo_git_dir(directory) / "index"
    if not index_file.exists():
        index_file.parent.mkdir(parents=True, exist_ok=True)
        repo_index = repo.git_dir / "index"
        if repo_index.exists():
            shutil.copyfile(repo_index, index_file)
    return index_file


def _plain_git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [*GIT, *args], cwd=cwd, env=env, capture_output=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise SiloError(f"git {args[0]} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout


def _has_object(repo: Path, name: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", name], cwd=repo, capture_output=True, check=False
    )
    return result.returncode == 0


@dataclass(frozen=True)
class Submodule:
    path: str
    url: str
    commit: str


def resolve_submodule_url(parent_url: str, url: str) -> str:
    """.gitmodules may give a URL relative to the parent repository, such as ../fmt.git."""
    if not url.startswith(("./", "../")):
        return url
    base = parent_url.rstrip("/")
    while url.startswith(("./", "../")):
        if url.startswith("../"):
            base = base.rsplit("/", 1)[0]
        url = url.split("/", 1)[1]
    return f"{base}/{url}"


def _submodules(repo: Path, commit: str, parent_url: str) -> list[Submodule]:
    """The submodules a commit pins: path and URL from .gitmodules, commit from the tree."""
    if not _has_object(repo, f"{commit}:.gitmodules"):
        return []
    settings: dict[str, dict[str, str]] = {}
    listing = _plain_git(
        repo, "config", "--blob", f"{commit}:.gitmodules", "--get-regexp", r"\.(path|url)$"
    )
    for line in listing.splitlines():
        key, _, value = line.partition(" ")
        name, _, field = key.removeprefix("submodule.").rpartition(".")
        settings.setdefault(name, {})[field] = value

    found = []
    for entry in settings.values():
        if "path" not in entry or "url" not in entry:
            continue
        tree_entry = _plain_git(repo, "ls-tree", commit, "--", entry["path"]).split()
        if len(tree_entry) >= 3 and tree_entry[1] == "commit":
            url = resolve_submodule_url(parent_url, entry["url"])
            found.append(Submodule(entry["path"], url, tree_entry[2]))
    return found


def _wanted_submodules(
    available: list[Submodule], wanted: bool | Sequence[str], url: str
) -> list[Submodule]:
    if wanted is True:
        return available
    by_path = {submodule.path: submodule for submodule in available}
    unknown = [path for path in wanted or () if path not in by_path]
    if unknown:
        raise SiloError(
            f"{url} has no submodule at {', '.join(unknown)}. "
            f"It has: {', '.join(sorted(by_path)) or 'none'}"
        )
    return [by_path[path] for path in wanted or ()]


def fetch_commit(
    url: str, commit: str, dest: Path, submodules: bool | Sequence[str] = False
) -> None:
    """Put the files of one commit of a remote repository into `dest`, without a .git folder.

    `submodules` is True for all of them or a list of their paths. A submodule that is
    fetched brings its own submodules with it.
    """
    key = xxhash.xxh128(url.encode()).hexdigest()[:16]
    repo = git_sources_dir() / key
    if not (repo / "HEAD").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _plain_git(repo, "init", "--bare", "--quiet")
    if not _has_object(repo, commit + "^{commit}"):
        retrying(
            f"Fetching {url}",
            lambda: _plain_git(repo, "fetch", "--quiet", "--depth", "1", url, commit),
            gives_up=lambda error: not isinstance(error, SiloError),
        )

    dest.mkdir(parents=True, exist_ok=True)
    index_file = dest.with_name(dest.name + ".index")
    env = os.environ | {
        "GIT_DIR": str(repo),
        "GIT_WORK_TREE": str(dest),
        "GIT_INDEX_FILE": str(index_file),
    }
    # autocrlf off, so the files match what upstream committed on every platform
    _plain_git(dest, "-c", "core.autocrlf=false", "read-tree", "--reset", "-u", commit, env=env)
    index_file.unlink()

    if submodules:
        available = _submodules(repo, commit, url)
        for submodule in _wanted_submodules(available, submodules, url):
            fetch_commit(submodule.url, submodule.commit, dest / submodule.path, submodules=True)


def snapshot_tree(directory: Path) -> str:
    """The git tree hash of the folder as it is on disk right now."""
    directory = directory.resolve()
    repo = _require_repo(directory)
    index_file = _snapshot_index(repo, directory)
    relative = directory.relative_to(repo.top).as_posix()

    _git(repo, repo.top, index_file, "add", "--all", "--", relative)
    if relative == ".":
        return _git(repo, repo.top, index_file, "write-tree")
    return _git(repo, repo.top, index_file, "write-tree", f"--prefix={relative}/")


def checkout_tree(directory: Path, tree: str, dest: Path, index_file: Path) -> None:
    """Make `dest` match a snapshot of `directory`.

    Only files that differ are rewritten, so the rest keep their timestamps. Files changed in
    `dest` since the last checkout (by a recipe's patch()) are restored first.
    """
    repo = _require_repo(directory.resolve())
    dest.mkdir(parents=True, exist_ok=True)
    _git(repo, dest, index_file, "read-tree", "--reset", "-u", tree)
