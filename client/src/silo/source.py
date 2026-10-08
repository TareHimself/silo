import hashlib
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from silo.errors import SiloError
from silo.git_snapshot import snapshot_tree
from silo.paths import cache_dir


@dataclass
class SourceSpec:
    """Where a recipe's source() says the source comes from."""

    kind: str | None = None
    url: str | None = None
    sha256: str | None = None
    local_path: str | None = None
    local_dir: Path | None = None
    tree: str | None = None

    def fetch(self, url: str, sha256: str) -> None:
        self.kind = "fetched"
        self.url = url
        self.sha256 = sha256.lower()

    def git(self, url: str, tag: str) -> None:
        raise NotImplementedError("src.git is not implemented yet")

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
    def id(self) -> str:
        if self.kind == "fetched":
            return f"fetched:{self.sha256}"
        if self.kind == "local" and self.tree:
            return f"local:{self.tree}"
        raise SiloError("The recipe's source() declared no source")


class SourceTree:
    """The work copy of the source, as a recipe's patch() sees it."""

    def __init__(self, root: Path, recipe_dir: Path) -> None:
        self.root = root
        self.recipe_dir = recipe_dir

    def apply(self, patch: str) -> None:
        patch_file = (self.recipe_dir / patch).resolve()
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_file)],
            cwd=self.root,
            check=True,
        )

    def remove(self, path: str) -> None:
        target = self.root / path
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()


def sha256_of(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def download(url: str, sha256: str) -> Path:
    file_name = url.rsplit("/", 1)[-1]
    archive = cache_dir() / "downloads" / f"{sha256[:16]}-{file_name}"
    if archive.exists():
        return archive

    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_name(archive.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "silo"})
    with urllib.request.urlopen(request) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out)

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


def unpack_fetched(spec: SourceSpec, dest: Path) -> None:
    assert spec.url is not None and spec.sha256 is not None
    archive = download(spec.url, spec.sha256)

    unpacked = dest.with_name(dest.name + ".unpack")
    if unpacked.exists():
        shutil.rmtree(unpacked)
    shutil.unpack_archive(archive, unpacked, filter="data")

    _unpacked_root(unpacked).rename(dest)
    if unpacked.exists():
        unpacked.rmdir()
