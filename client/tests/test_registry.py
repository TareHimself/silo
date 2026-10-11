import subprocess
from pathlib import Path

import pytest

from silo import registry
from silo.build_id import recipe_hash
from silo.dependency_graph import resolve
from silo.enums import BuildMode
from silo.errors import ResolutionError, SiloError
from silo.registry import RecipeLookup
from silo.source import fetch_source

RECIPE = """\
from silo import SiloPackage


class Demo(SiloPackage):
    name = "{name}"
    version = "{version}"

    def deps(self):
        {deps}
"""


def write_recipe(folder: Path, name: str, version: str, deps: str = "pass") -> Path:
    folder.mkdir(parents=True)
    text = RECIPE.format(name=name, version=version, deps=deps)
    (folder / "silopkg.py").write_text(text, encoding="utf-8", newline="\n")
    return folder


def publish(registry: Path, name: str, version: str, deps: str = "pass") -> None:
    write_recipe(registry / "recipes" / name / version, name, version, deps)


@pytest.fixture
def project(tmp_path):
    """A project folder whose config lists the registries given, in order."""

    def make(*registries: str, deps: str) -> Path:
        root = tmp_path / "project"
        entries = "".join(f"[[registry]]\n{registry}\n" for registry in registries)
        root.mkdir()
        (root / "silo.config.toml").write_text(entries, encoding="utf-8")
        return write_recipe(root / "app", "app", "1.0", deps)

    return make


def test_a_named_dependency_comes_from_the_registry(project, tmp_path):
    publish(tmp_path / "registry", "zlib", "1.3.1")
    publish(tmp_path / "registry", "freetype", "2.13.3", 'self.dep("zlib@1.3.1")')
    app = project('name = "local"\npath = "../registry"', deps='self.dep("freetype@2.13.3")')

    graph = resolve(app, BuildMode.Release)

    assert [node.name for node in graph.build_order()] == ["zlib", "freetype", "app"]
    assert graph.nodes["zlib"].version == "1.3.1"


def test_a_tool_can_be_named_too(project, tmp_path):
    publish(tmp_path / "registry", "protoc", "30.0")
    app = project(
        'name = "local"\npath = "../registry"',
        deps='self.tool("protoc@30.0"); self.tool("cmake@4.3")',
    )

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["app"].tool_names == ["protoc"]


def test_a_missing_version_lists_the_ones_there_are(project, tmp_path):
    publish(tmp_path / "registry", "zlib", "1.3.1")
    app = project('name = "local"\npath = "../registry"', deps='self.dep("zlib@1.2")')

    with pytest.raises(ResolutionError, match=r"only has zlib 1\.3\.1"):
        resolve(app, BuildMode.Release)


def test_a_name_needs_a_version_and_a_registry(project, tmp_path):
    with pytest.raises(ResolutionError, match='Write "zlib@<version>"'):
        resolve(project(deps='self.dep("zlib")'), BuildMode.Release)
    orphan = write_recipe(tmp_path / "orphan", "orphan", "1.0", 'self.dep("zlib@1.3.1")')
    with pytest.raises(ResolutionError, match=r"no silo\.config\.toml"):
        resolve(orphan, BuildMode.Release)


def test_the_first_registry_with_the_name_decides(project, tmp_path):
    publish(tmp_path / "mine", "zlib", "1.3.1")
    publish(tmp_path / "public", "zlib", "9.9")
    app = project(
        'name = "mine"\npath = "../mine"',
        'name = "public"\npath = "../public"',
        deps='self.dep("zlib@9.9")',
    )

    with pytest.raises(ResolutionError, match=r"only has zlib 1\.3\.1"):
        resolve(app, BuildMode.Release)


def test_a_recipe_in_the_wrong_folder_is_reported(project, tmp_path):
    write_recipe(tmp_path / "registry" / "recipes" / "zlib" / "1.3.1", "zlib", "1.2")
    app = project('name = "local"\npath = "../registry"', deps='self.dep("zlib@1.3.1")')

    with pytest.raises(ResolutionError, match=r"should hold zlib 1\.3\.1"):
        resolve(app, BuildMode.Release)


def test_a_registry_entry_needs_exactly_one_source(tmp_path):
    (tmp_path / "silo.config.toml").write_text('[[registry]]\nname = "both"\n', encoding="utf-8")

    with pytest.raises(SiloError, match="either path or git"):
        RecipeLookup.load(tmp_path)


def git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    result = subprocess.run(
        ["git", *identity, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def upstream(tmp_path):
    repo = tmp_path / "upstream"
    publish(repo, "zlib", "1.3.1")
    git(repo, "init", "--quiet")
    commit_all(repo, "zlib")
    return repo


def depend_on(app: Path, spec: str) -> None:
    text = RECIPE.format(name="app", version="1.0", deps=f'self.dep("{spec}")')
    (app / "silopkg.py").write_text(text, encoding="utf-8", newline="\n")


def next_run() -> None:
    """silo asks a followed registry where it is once per run."""
    registry._latest.clear()


def test_a_followed_git_registry_picks_up_new_commits(project, upstream):
    app = project(f'name = "remote"\ngit = "{upstream.as_uri()}"', deps='self.dep("zlib@1.3.1")')

    assert "zlib" in resolve(app, BuildMode.Release).nodes

    publish(upstream, "expat", "2.6.4")
    commit_all(upstream, "expat")
    depend_on(app, "expat@2.6.4")
    next_run()

    assert "expat" in resolve(app, BuildMode.Release).nodes


def test_a_pinned_git_registry_stays_on_its_commit(project, upstream):
    pinned = git(upstream, "rev-parse", "HEAD")
    publish(upstream, "expat", "2.6.4")
    commit_all(upstream, "expat")
    source = f'name = "remote"\ngit = "{upstream.as_uri()}"\nrev = "{pinned}"'
    app = project(source, deps='self.dep("expat@2.6.4")')

    with pytest.raises(ResolutionError, match="which no registry has"):
        resolve(app, BuildMode.Release)


def test_a_registry_that_cannot_be_reached_uses_its_last_copy(project, upstream, capsys):
    app = project(f'name = "remote"\ngit = "{upstream.as_uri()}"', deps='self.dep("zlib@1.3.1")')
    resolve(app, BuildMode.Release)
    upstream.rename(upstream.with_name("gone"))
    next_run()

    assert "zlib" in resolve(app, BuildMode.Release).nodes
    assert "cannot be reached" in capsys.readouterr().out


def test_a_recipe_hashes_the_same_from_a_working_copy_and_from_a_git_registry(upstream):
    fetched = registry.Registry("remote", git=upstream.as_uri())
    recipe = "recipes/zlib/1.3.1"

    assert recipe_hash(fetched.root / recipe, False) == recipe_hash(upstream / recipe, False)


LOCAL_RECIPE = """\
from silo import SiloPackage


class Webmdx(SiloPackage):
    name = "webmdx"
    version = "1.0.0"

    def source(self, src):
        src.local(".")
"""


@pytest.fixture
def library(tmp_path):
    """A library that keeps its recipe in its own repository and builds the folder it is in."""
    repo = tmp_path / "webmdx"
    repo.mkdir()
    (repo / "silopkg.py").write_text(LOCAL_RECIPE, encoding="utf-8", newline="\n")
    (repo / "decoder.cpp").write_text("// code", encoding="utf-8", newline="\n")
    git(repo, "init", "--quiet")
    commit_all(repo, "first")
    return repo


def configure(app: Path, text: str) -> None:
    (app.parent / "silo.config.toml").write_text(text, encoding="utf-8")


def test_a_package_can_be_taken_from_a_folder(project, library, tmp_path):
    publish(tmp_path / "registry", "webmdx", "0.5")
    app = project(deps='self.dep("webmdx@1.0.0")')
    configure(
        app,
        '[[registry]]\nname = "local"\npath = "../registry"\n'
        '[package.webmdx]\npath = "../webmdx"\n',
    )

    node = resolve(app, BuildMode.Release).nodes["webmdx"]

    assert node.version == "1.0.0"
    assert node.source.local_source


def test_a_package_from_a_git_commit_builds_that_commits_folder(project, library, tmp_path):
    commit = git(library, "rev-parse", "HEAD")
    (library / "decoder.cpp").write_text("// newer code", encoding="utf-8", newline="\n")
    commit_all(library, "second")
    app = project(deps='self.dep("webmdx")')
    configure(app, f'[package.webmdx]\ngit = "{library.as_uri()}"\nrev = "{commit}"\n')

    source = resolve(app, BuildMode.Release).nodes["webmdx"].source
    fetch_source(source, tmp_path / "src")

    assert not source.local_source
    assert source.id == f"fetched:{library.as_uri()}@{commit}:."
    assert (tmp_path / "src" / "decoder.cpp").read_text(encoding="utf-8") == "// code"


def test_a_package_entry_needs_a_recipe_where_it_points(project):
    app = project(deps='self.dep("webmdx@1.0.0")')
    configure(app, '[package.webmdx]\npath = "../nowhere"\n')

    with pytest.raises(ResolutionError, match=r"has no silopkg\.py"):
        resolve(app, BuildMode.Release)


def located(library: Path, commit: str) -> str:
    return f'self.dep("webmdx@1.0.0", git="{library.as_uri()}", commit="{commit}")'


def test_a_recipe_can_say_which_commit_holds_a_dependencys_recipe(project, library, tmp_path):
    commit = git(library, "rev-parse", "HEAD")
    app = project(deps=located(library, commit))

    source = resolve(app, BuildMode.Release).nodes["webmdx"].source

    assert source.id == f"fetched:{library.as_uri()}@{commit}:."


def test_the_projects_config_wins_over_a_recipes_location(project, library, tmp_path):
    fork = tmp_path / "fork"
    write_recipe(fork, "webmdx", "1.0.0")
    app = project(deps=located(library, git(library, "rev-parse", "HEAD")))
    configure(app, '[package.webmdx]\npath = "../fork"\n')

    graph = resolve(app, BuildMode.Release)

    assert graph.nodes["webmdx"].package.recipe_dir == fork.resolve()


def test_a_recipe_cannot_follow_a_branch(project, library):
    app = project(deps=f'self.dep("webmdx@1.0.0", git="{library.as_uri()}", commit="main")')

    with pytest.raises(SiloError, match="needs commit=<full hash>"):
        resolve(app, BuildMode.Release)


def test_two_recipes_that_disagree_on_a_commit_are_told_how_to_settle_it(
    project, library, tmp_path
):
    first = git(library, "rev-parse", "HEAD")
    (library / "decoder.cpp").write_text("// newer code", encoding="utf-8", newline="\n")
    second = commit_all(library, "second")
    publish(tmp_path / "registry", "player", "1.0", located(library, second))
    app = project(deps=f'self.dep("player@1.0"); {located(library, first)}')
    configure(app, '[[registry]]\nname = "local"\npath = "../registry"\n')

    with pytest.raises(ResolutionError, match=r"\[package\.webmdx\] entry"):
        resolve(app, BuildMode.Release)
