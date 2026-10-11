import os
from pathlib import Path


def silo_home() -> Path:
    override = os.environ.get("SILO_HOME")
    return Path(override) if override else Path.home() / ".silo"


def profiles_dir() -> Path:
    return silo_home() / "profiles"


def profile_path(name: str) -> Path:
    return profiles_dir() / f"{name}.toml"


def store_dir() -> Path:
    return silo_home() / "store"


def cache_dir() -> Path:
    """Everything under here can be deleted at any time. silo recreates what it needs."""
    return silo_home() / "cache"


def builds_dir() -> Path:
    return cache_dir() / "builds"


def downloads_dir() -> Path:
    return cache_dir() / "downloads"


def git_sources_dir() -> Path:
    return cache_dir() / "git"


def snapshots_dir() -> Path:
    return cache_dir() / "snapshots"


def conan_dir() -> Path:
    return cache_dir() / "conan"
