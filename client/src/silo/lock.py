from silo.silo_package import SiloPackage
from pathlib import Path

class LockInfo:
    def __init__(self,file_path: Path,lock_id: str) -> None:
        self.file_path = file_path
        self.lock_id = lock_id

def ensure_lock(package: SiloPackage) -> LockInfo:
    """
    creates or gets a lockfile then returns the lock id based on the package configuration
    """
    

    raise NotImplementedError()