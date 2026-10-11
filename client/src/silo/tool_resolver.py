import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from silo.dependency import Dependency
from silo.paths import store_dir
from silo.versions import matches_prefix, version_key

# Where each PyPI wheel keeps its real executable, relative to the install folder
UV_TOOL_BIN = {
    "cmake": "cmake/data/bin",
    "ninja": "bin",
    "conan": "bin",
    "meson": "bin",
    "pkgconf": "pkgconf/.bin",
}

STORE_SUFFIX = "-uv"


@dataclass
class ResolvedTool:
    name: str
    version: str
    root: Path

    @property
    def bin_dir(self) -> Path:
        return self.root / UV_TOOL_BIN[self.name]


def _store_path(name: str, version: str) -> Path:
    return store_dir() / f"{name}-{version}{STORE_SUFFIX}"


def _find_installed(tool: Dependency) -> ResolvedTool | None:
    """The highest version already in the store that satisfies the request."""
    candidates = []
    for directory in store_dir().glob(f"{tool.name}-*{STORE_SUFFIX}"):
        version = directory.name.removeprefix(f"{tool.name}-").removesuffix(STORE_SUFFIX)
        if matches_prefix(version, tool.version):
            candidates.append(ResolvedTool(tool.name, version, directory))
    return max(candidates, key=lambda candidate: version_key(candidate.version), default=None)


def _installed_version(install_dir: Path, name: str) -> str:
    dist_info = next(install_dir.glob(f"{name}-*.dist-info"))
    return dist_info.name.removeprefix(f"{name}-").removesuffix(".dist-info")


def _install(tool: Dependency) -> ResolvedTool:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is not on PATH")

    requirement = f"{tool.name}=={tool.version}.*" if tool.version else tool.name
    store_dir().mkdir(parents=True, exist_ok=True)
    staging = store_dir() / f".tmp-{uuid.uuid4().hex}"
    try:
        install = [uv, "pip", "install", "--quiet", "--python", sys.executable]
        subprocess.run([*install, "--target", str(staging), requirement], check=True)
        version = _installed_version(staging, tool.name)
        final = _store_path(tool.name, version)
        if not final.exists():
            staging.rename(final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return ResolvedTool(tool.name, version, final)


def is_fetched_tool(tool: Dependency) -> bool:
    """True for a ready-made program such as "cmake@4.3". Anything else is a recipe."""
    return tool.path is None and tool.git is None and tool.name in UV_TOOL_BIN


def resolve_tool(tool: Dependency) -> ResolvedTool:
    if tool.name not in UV_TOOL_BIN:
        raise RuntimeError(f"No provider for tool '{tool.name}'")
    return _find_installed(tool) or _install(tool)
