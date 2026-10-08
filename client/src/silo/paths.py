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


def work_dir() -> Path:
    return silo_home() / "work"


def cache_dir() -> Path:
    return silo_home() / "cache"
