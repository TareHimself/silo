import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from silo import paths
from silo.errors import SiloError


@dataclass(frozen=True)
class Cache:
    name: str
    description: str
    directory: Callable[[], Path]


CACHES = (
    Cache("builds", "source copies and build trees of packages", paths.builds_dir),
    Cache("downloads", "archives fetched by src.fetch", paths.downloads_dir),
    Cache("git", "repositories fetched by src.git", paths.git_sources_dir),
    Cache("snapshots", "snapshots of local sources", paths.snapshots_dir),
    Cache("conan", "what ConanInstall downloaded and built", paths.conan_dir),
)


def find_caches(names: list[str]) -> list[Cache]:
    """The caches with these names, or all of them when no name is given."""
    if not names:
        return list(CACHES)
    by_name = {cache.name: cache for cache in CACHES}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise SiloError(f"No cache named {', '.join(unknown)}. There are: {', '.join(by_name)}")
    return [by_name[name] for name in names]


def size_of(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def _remove_read_only(function, path, _error) -> None:
    # git marks its object files read-only, which stops Windows from deleting them
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(directory: Path) -> None:
    if directory.exists():
        shutil.rmtree(directory, onexc=_remove_read_only)


def clear(cache: Cache) -> int:
    """Delete a cache and return how many bytes that freed."""
    directory = cache.directory()
    freed = size_of(directory)
    remove_tree(directory)
    return freed


def format_size(size: int) -> str:
    amount = float(size)
    for unit in ("B", "KB", "MB"):
        if amount < 1024:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"
