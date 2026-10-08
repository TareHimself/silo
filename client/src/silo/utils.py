import inspect
from importlib.util import spec_from_file_location, module_from_spec
from typing import Optional
from silo.silo_package import SiloPackage
from pathlib import Path

def get_package_file_path(directory: Path):
    return Path(directory) / "silopkg.py"

def get_lock_file_path(directory: Path):
    return Path(directory) / "silo.lock"

def load_package_cls(directory: Path) -> type[SiloPackage]:
    file_Path = get_package_file_path(directory)
    spec = spec_from_file_location("silopkg",file_Path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load silopkg from path {directory}")
    
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    package: Optional[type[SiloPackage]] = None
    for _,obj in inspect.getmembers(module,inspect.isclass):
        if issubclass(obj,SiloPackage) and obj is not SiloPackage and obj.__module__ == module.__name__:
            package = obj

    if package is None:
        raise RuntimeError(f"Found no package in {file_Path}")
    
    return package

def get_package_silo_dir(package: SiloPackage):
    return package._path.parent / ".silo"
