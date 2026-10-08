"""Hash and copy a folder's current contents through git, without touching the user's repo.

A snapshot covers tracked and untracked files and respects .gitignore. It never needs a commit:
silo keeps its own index file and writes new objects into its own cache.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import xxhash

from silo.errors import SiloError
from silo.paths import cache_dir


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
    return cache_dir() / "git" / key


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
        ["git", *args], cwd=work_tree, env=env, capture_output=True, encoding="utf-8", check=False
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
