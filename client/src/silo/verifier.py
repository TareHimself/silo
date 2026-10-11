"""Checks that a package does not have its install location compiled in.

Every build installs to a made-up prefix such as /silo-prefix-<key>. If that text shows up
inside a packaged file, the library will look for files at a path that never exists.
"""

from pathlib import Path

from silo.errors import SiloError

CHUNK_SIZE = 1 << 20


def _contains(path: Path, needles: list[bytes]) -> bool:
    overlap = max(len(needle) for needle in needles) - 1
    carried = b""
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            window = carried + chunk
            if any(needle in window for needle in needles):
                return True
            carried = window[-overlap:]
    return False


def files_containing(package_dir: Path, text: str) -> list[str]:
    """Package files that contain `text`, as plain or as wide (UTF-16) characters."""
    needles = [text.encode("utf-8"), text.encode("utf-16-le")]
    return [
        path.relative_to(package_dir).as_posix()
        for path in sorted(package_dir.rglob("*"))
        if path.is_file() and _contains(path, needles)
    ]


def verify_no_install_prefix(package_dir: Path, name: str, install_prefix: str) -> None:
    sentinel = install_prefix.strip("/")
    leaking = files_containing(package_dir, sentinel)
    if leaking:
        raise SiloError(
            f"{name} has its install prefix ({sentinel}) compiled into: {', '.join(leaking)}. "
            "It would look for files at a path that does not exist. Turn the offending "
            "feature off in the recipe's build(), or fix it in patch()."
        )
