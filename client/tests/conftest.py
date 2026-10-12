import subprocess
from pathlib import Path

import pytest

from silo import retry
from silo.build_profile import CompilerProfile, Profile, Settings
from silo.enums import Architecture, Compiler, Platform
from silo.options import Options
from silo.silo_package import SiloPackage
from silo.utils import load_package_cls

RECIPE_HEADER = """\
from silo import Options, SiloPackage


class Demo(SiloPackage[Options]):
    name = "demo"
    version = "1.0"
"""


@pytest.fixture(autouse=True)
def isolated_silo_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SILO_HOME", str(tmp_path_factory.mktemp("silo-home")))


@pytest.fixture(autouse=True)
def no_waiting_between_retries(monkeypatch):
    monkeypatch.setattr(retry, "DELAYS", (0.0, 0.0))


@pytest.fixture
def git_repo(tmp_path):
    """An empty git repository. Nothing is committed, which silo's snapshots do not need."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    return repo


@pytest.fixture
def windows_profile() -> Profile:
    return Profile(
        settings=Settings(os=Platform.Windows, arch=Architecture.X86_64),
        compiler=CompilerProfile(
            kind=Compiler.MSVC,
            executable=Path("C:/msvc/cl.exe"),
            version="14.51.36231",
            target="x86_64-pc-windows-msvc",
            sdk="10.0.26100.0",
        ),
    )


@pytest.fixture
def linux_profile() -> Profile:
    return Profile(
        settings=Settings(os=Platform.Linux, arch=Architecture.X86_64),
        compiler=CompilerProfile(
            kind=Compiler.GCC,
            executable=Path("/usr/bin/gcc"),
            cxx_executable=Path("/usr/bin/g++"),
            version="13.3.0",
            target="x86_64-linux-gnu",
        ),
    )


@pytest.fixture
def load_demo_recipe(tmp_path):
    def load(extra_class_body: str = "") -> SiloPackage:
        recipe_dir = tmp_path / "demo"
        recipe_dir.mkdir(exist_ok=True)
        recipe = recipe_dir / "silopkg.py"
        recipe.write_text(RECIPE_HEADER + extra_class_body, encoding="utf-8", newline="\n")
        return load_package_cls(recipe_dir)(recipe, Options())

    return load
