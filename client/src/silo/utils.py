import inspect
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from silo.silo_package import SiloPackage


def get_package_file_path(directory: Path):
    return Path(directory) / "silopkg.py"


def get_lock_file_path(directory: Path):
    return Path(directory) / "silo.lock"


def load_package_cls(directory: Path) -> type[SiloPackage]:
    file_Path = get_package_file_path(directory)
    spec = spec_from_file_location("silopkg", file_Path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load silopkg from path {directory}")

    module = module_from_spec(spec)
    # A recipe often sits in its own source tree, where a __pycache__ would be noise
    write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = write_bytecode

    package: type[SiloPackage] | None = None
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, SiloPackage)
            and obj is not SiloPackage
            and obj.__module__ == module.__name__
        ):
            package = obj

    if package is None:
        raise RuntimeError(f"Found no package in {file_Path}")

    return package


def get_package_silo_dir(package: SiloPackage):
    return package._path.parent / ".silo"
