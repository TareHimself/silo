import hashlib
import http.client
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from silo.errors import SiloError
from silo.git_snapshot import fetch_commit, snapshot_tree
from silo.paths import downloads_dir
from silo.retry import retrying

FULL_COMMIT = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
# Answers that say the file is not there or not ours to have, which asking again never changes
FINAL_HTTP_STATUSES = frozenset({400, 401, 403, 404, 410})


@dataclass
class SourceSpec:
    """Where a recipe's source() says the source comes from."""

    kind: str | None = None
    url: str | None = None
    sha256: str | None = None
    commit: str | None = None
    submodules: bool | tuple[str, ...] = False
    local_path: str | None = None
    local_dir: Path | None = None
    tree: str | None = None

    def fetch(self, url: str, sha256: str) -> None:
        self.kind = "fetched"
        self.url = url
        self.sha256 = sha256.lower()

    def git(
        self,
        url: str,
        commit: str | None = None,
        tag: str | None = None,
        submodules: bool | Sequence[str] = False,
    ) -> None:
        """A git repository at one exact commit, given as its full hash.

        `submodules` is True for all of them, or a list of the paths to fetch.
        """
        if tag is not None or commit is None:
            raise SiloError(
                "src.git needs commit=<full hash>. A tag can move, and pinning one needs the "
                "lockfile, which is not built yet."
            )
        if not FULL_COMMIT.fullmatch(commit):
            raise SiloError(f"src.git needs the full commit hash, not {commit!r}")
        self.kind = "git"
        self.url = url
        self.commit = commit.lower()
        self.submodules = submodules if isinstance(submodules, bool) else tuple(submodules)

    def empty(self) -> None:
        """No source at all, for a recipe whose build fetches a finished package."""
        self.kind = "empty"

    def copy_of(self, folder: Path, identity: str) -> None:
        """A folder that never changes, such as part of a fetched commit, named by `identity`."""
        self.kind = "copied"
        self.local_dir = folder
        self.tree = identity

    def local(self, path: str = ".") -> None:
        """A folder on disk, relative to the recipe. It must be inside a git repository."""
        self.kind = "local"
        self.local_path = path

    def snapshot_local(self, base_dir: Path) -> None:
        """Pin a local source to the tree hash of what is on disk right now."""
        assert self.local_path is not None
        self.local_dir = (base_dir / self.local_path).resolve()
        self.tree = snapshot_tree(self.local_dir)

    @property
    def local_source(self) -> bool:
        return self.kind == "local"

    @property
    def holds_the_recipe(self) -> bool:
        """True when the recipe builds the folder it sits in, so the source covers both."""
        return self.kind in ("local", "copied")

    @property
    def id(self) -> str:
        if self.kind == "fetched":
            return f"fetched:{self.sha256}"
        if self.kind == "git":
            if not self.submodules:
                return f"fetched:{self.commit}"
            chosen = "all" if self.submodules is True else ",".join(sorted(self.submodules))
            return f"fetched:{self.commit}+submodules:{chosen}"
        if self.kind == "empty":
            return "empty"
        if self.kind == "copied":
            return f"fetched:{self.tree}"
        if self.kind == "local" and self.tree:
            return f"local:{self.tree}"
        raise SiloError("The recipe's source() declared no source")


class SourceTree:
    """The work copy of the source, as a recipe's patch() sees it."""

    def __init__(self, root: Path, recipe_dir: Path) -> None:
        self.root = root
        self.recipe_dir = recipe_dir

    def apply(self, patch: str) -> None:
        """Apply a patch file, given relative to the recipe."""
        patch_file = (self.recipe_dir / patch).resolve()
        if not patch_file.is_file():
            raise SiloError(f"Patch file not found: {patch_file}")
        # Without the ceiling, git would treat an enclosing repository as the tree to patch
        env = os.environ | {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_file)],
            cwd=self.root,
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            reason = result.stderr.strip()
            raise SiloError(f"{patch} does not apply to {self.root}: {reason}")

    def replace(self, path: str, old: str, new: str) -> None:
        """Swap one piece of text in a file, for changes too small to be worth a patch file."""
        target = self.root / path
        if not target.is_file():
            raise SiloError(f"Cannot edit '{path}': it is not in {self.root}")
        text = target.read_text(encoding="utf-8")
        if old not in text:
            raise SiloError(f"Cannot edit '{path}': it does not contain {old!r}")
        target.write_text(text.replace(old, new), encoding="utf-8", newline="")

    def remove(self, path: str) -> None:
        """Delete a file or folder, given relative to the source root."""
        target = self.root / path
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise SiloError(f"Cannot remove '{path}': it is not in {self.root}")


def sha256_of(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def download(url: str, sha256: str) -> Path:
    file_name = url.rsplit("/", 1)[-1]
    archive = downloads_dir() / f"{sha256[:16]}-{file_name}"
    if archive.exists():
        return archive

    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_name(archive.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "silo"})

    def attempt() -> None:
        with urllib.request.urlopen(request) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)

    def is_final(error: Exception) -> bool:
        if isinstance(error, urllib.error.HTTPError):
            return error.code in FINAL_HTTP_STATUSES
        return not isinstance(error, (OSError, http.client.HTTPException))

    retrying(f"Downloading {url}", attempt, gives_up=is_final)

    actual = sha256_of(partial)
    if actual != sha256:
        partial.unlink()
        raise SiloError(f"sha256 mismatch for {url}\n  expected {sha256}\n  actual   {actual}")
    partial.rename(archive)
    return archive


def _unpacked_root(unpacked: Path) -> Path:
    """Most archives wrap everything in one folder, such as zlib-1.3.1/."""
    entries = list(unpacked.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return unpacked


def fetch_source(spec: SourceSpec, dest: Path) -> None:
    """Put a tarball or git source into `dest`. Local source goes through a git snapshot."""
    if spec.kind == "empty":
        dest.mkdir(parents=True)
        return
    if spec.kind == "copied":
        assert spec.local_dir is not None
        shutil.copytree(spec.local_dir, dest)
        return
    assert spec.url is not None
    if spec.kind == "git":
        assert spec.commit is not None
        fetch_commit(spec.url, spec.commit, dest, spec.submodules)
        return

    assert spec.sha256 is not None
    archive = download(spec.url, spec.sha256)

    unpacked = dest.with_name(dest.name + ".unpack")
    if unpacked.exists():
        shutil.rmtree(unpacked)
    shutil.unpack_archive(archive, unpacked, filter="data")

    _unpacked_root(unpacked).rename(dest)
    if unpacked.exists():
        unpacked.rmdir()
