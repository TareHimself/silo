import shutil
import subprocess

import pytest

from silo.builder import WorkDirs, prepare_source
from silo.dependency_graph import resolve
from silo.enums import BuildMode
from silo.errors import ResolutionError, SiloError
from silo.git_snapshot import fetch_commit
from silo.source import SourceSpec

COMMIT = "9f2c41d0a1b2c3d4e5f60718293a4b5c6d7e8f90"

GIT_RECIPE = """\
from silo import SiloPackage


class Demo(SiloPackage):
    name = "demo"
    version = "1.0"

    def source(self, src):
        src.git("{url}", commit="{commit}")

    def patch(self, src):
        src.remove("bundled")
"""

FETCHED_RECIPE = """\
from silo import SiloPackage


class Zlib(SiloPackage):
    name = "zlib"
    version = "1.3.1"

    def source(self, src):
        src.fetch("https://example.com/zlib.tar.gz", sha256="aa")
"""

APP_RECIPE = """\
from silo import SiloPackage


class App(SiloPackage):
    name = "app"
    version = "1.0"

    def source(self, src):
        src.fetch("https://example.com/app.tar.gz", sha256="bb")

    def deps(self):
        self.dep("../zlib")
        {extra}
"""


def write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def git(repo, *args: str) -> str:
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    result = subprocess.run(
        ["git", *identity, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def upstream(git_repo):
    """A repository with one commit, standing in for a library's upstream."""
    write(git_repo / "lib.c", "int lib;\n")
    write(git_repo / "bundled" / "zlib.c", "int z;\n")
    git(git_repo, "add", "--all")
    git(git_repo, "commit", "--quiet", "-m", "first")
    return git_repo, git(git_repo, "rev-parse", "HEAD")


def test_fetch_commit_writes_the_files_without_a_git_folder(upstream, tmp_path):
    repo, commit = upstream

    fetch_commit(repo.as_uri(), commit, tmp_path / "out")

    assert (tmp_path / "out" / "lib.c").read_text(encoding="utf-8") == "int lib;\n"
    assert not (tmp_path / "out" / ".git").exists()
    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith("out")) == [
        "out"
    ]


def test_a_commit_already_fetched_comes_from_the_cache(upstream, tmp_path):
    repo, commit = upstream
    url = repo.as_uri()
    fetch_commit(url, commit, tmp_path / "first")
    shutil.rmtree(repo, ignore_errors=True)

    fetch_commit(url, commit, tmp_path / "second")

    assert (tmp_path / "second" / "lib.c").is_file()


def test_fetching_a_commit_that_does_not_exist_is_an_error(upstream, tmp_path):
    repo, _ = upstream

    with pytest.raises(SiloError, match="git fetch failed"):
        fetch_commit(repo.as_uri(), COMMIT, tmp_path / "out")


def test_git_source_id_is_the_commit():
    source = SourceSpec()
    source.git("https://example.com/lib.git", commit=COMMIT.upper())

    assert source.id == f"fetched:{COMMIT}"
    assert not source.local_source


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"tag": "v1.0"}, "needs commit="),
        ({}, "needs commit="),
        ({"commit": "9f2c41d"}, "full commit hash"),
    ],
)
def test_git_source_needs_a_full_commit(arguments, message):
    with pytest.raises(SiloError, match=message):
        SourceSpec().git("https://example.com/lib.git", **arguments)


def test_a_recipe_with_a_git_source_is_fetched_and_patched(upstream, tmp_path):
    repo, commit = upstream
    recipe_dir = tmp_path / "recipe"
    write(recipe_dir / "silopkg.py", GIT_RECIPE.format(url=repo.as_uri(), commit=commit))
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    dirs = WorkDirs(tmp_path / "work")

    prepare_source(node, dirs)

    assert (dirs.source / "lib.c").is_file()
    assert not (dirs.source / "bundled").exists()


@pytest.fixture
def app_with_zlib(git_repo):
    def make(extra: str = "pass") -> None:
        write(git_repo / "app" / "silopkg.py", APP_RECIPE.format(extra=extra))
        write(git_repo / "zlib" / "silopkg.py", FETCHED_RECIPE)
        write(git_repo / "my-zlib" / "zlib.c", "int mine;\n")
        write(git_repo / "team-zlib" / "zlib.c", "int ours;\n")

    return make


def test_source_flag_builds_a_dependency_from_a_local_folder(git_repo, app_with_zlib):
    app_with_zlib()

    graph = resolve(git_repo / "app", BuildMode.Release, cli_sources={"zlib": git_repo / "my-zlib"})

    zlib = graph.nodes["zlib"]
    assert zlib.source.local_dir == (git_repo / "my-zlib").resolve()
    assert zlib.source.id.startswith("local:")
    assert zlib.overridden
    assert not graph.nodes["app"].source.local_source


def test_source_flag_beats_the_root_recipes_source_override(git_repo, app_with_zlib):
    app_with_zlib('self.override("zlib", source="../team-zlib")')
    without_flag = resolve(git_repo / "app", BuildMode.Release)
    assert without_flag.nodes["zlib"].source.local_dir == (git_repo / "team-zlib").resolve()

    with_flag = resolve(
        git_repo / "app", BuildMode.Release, cli_sources={"zlib": git_repo / "my-zlib"}
    )

    assert with_flag.nodes["zlib"].source.local_dir == (git_repo / "my-zlib").resolve()


def test_source_flag_for_a_package_outside_the_graph_is_an_error(git_repo, app_with_zlib):
    app_with_zlib()

    with pytest.raises(ResolutionError, match="--source names 'libpng'"):
        resolve(git_repo / "app", BuildMode.Release, cli_sources={"libpng": git_repo / "my-zlib"})


def test_a_source_that_was_only_half_fetched_is_fetched_again(upstream, tmp_path):
    repo, commit = upstream
    recipe_dir = tmp_path / "recipe"
    write(recipe_dir / "silopkg.py", GIT_RECIPE.format(url=repo.as_uri(), commit=commit))
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    dirs = WorkDirs(tmp_path / "work")
    write(dirs.source / "half-written.c", "int")

    prepare_source(node, dirs)

    assert (dirs.source / "lib.c").is_file()
    assert not (dirs.source / "half-written.c").exists()


def test_a_fetched_source_is_not_fetched_twice(upstream, tmp_path):
    repo, commit = upstream
    recipe_dir = tmp_path / "recipe"
    write(recipe_dir / "silopkg.py", GIT_RECIPE.format(url=repo.as_uri(), commit=commit))
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    dirs = WorkDirs(tmp_path / "work")
    prepare_source(node, dirs)
    write(dirs.source / "built-here.o", "object")

    prepare_source(node, dirs)

    assert (dirs.source / "built-here.o").is_file()
