import subprocess
from pathlib import Path

import pytest

from silo.affected import affected_entries, changed_entries
from silo.build_profile import Profile
from silo.errors import SiloError

RECIPE = """\
from silo import InvalidConfiguration, SiloPackage
from silo.enums import Platform


class Demo(SiloPackage):
    name = "{name}"
    version = "1.0"

    def deps(self):
        {deps}

    def validate(self):
        {validate}
"""
LINUX_ONLY = """if self.profile.settings.os is not Platform.Linux:
            raise InvalidConfiguration("Linux only")"""


def git(repo: Path, *args: str) -> None:
    identity = ["-c", "user.name=silo", "-c", "user.email=silo@example.com"]
    subprocess.run(["git", *identity, *args], cwd=repo, check=True, capture_output=True)


def publish(registry: Path, name: str, deps: str = "pass", validate: str = "pass") -> Path:
    folder = registry / "recipes" / name / "1.0"
    folder.mkdir(parents=True, exist_ok=True)
    text = RECIPE.format(name=name, deps=deps, validate=validate)
    (folder / "silopkg.py").write_text(text, encoding="utf-8", newline="\n")
    return folder


@pytest.fixture
def registry(tmp_path):
    """zlib, png which links it, app which links png, gen which app runs, and lone."""
    root = tmp_path / "registry"
    publish(root, "zlib")
    publish(root, "png", 'self.dep("zlib@1.0")')
    publish(root, "gen")
    publish(root, "app", 'self.dep("png@1.0"); self.tool("gen@1")')
    publish(root, "lone")
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "start")
    return root


@pytest.fixture
def names(linux_profile):
    def listed(root: Path, changed: set[Path] | None, profile: Profile = linux_profile):
        return [entry.parent.name for entry in affected_entries(root, changed, profile)]

    return listed


def touch(folder: Path) -> None:
    with (folder / "silopkg.py").open("a", encoding="utf-8", newline="\n") as recipe:
        recipe.write("# changed\n")


def test_a_change_reaches_everything_that_links_the_recipe(registry, names):
    touch(registry / "recipes" / "zlib" / "1.0")

    assert names(registry, changed_entries(registry, "main")) == ["app", "png", "zlib"]


def test_a_changed_tool_reaches_the_recipes_that_run_it(registry, names):
    touch(registry / "recipes" / "gen" / "1.0")

    assert names(registry, changed_entries(registry, "main")) == ["app", "gen"]


def test_nothing_changed_reaches_nothing(registry, names):
    assert names(registry, changed_entries(registry, "main")) == []


def test_a_committed_change_on_a_branch_is_compared_with_where_it_left(registry, names):
    git(registry, "checkout", "--quiet", "-b", "work")
    touch(registry / "recipes" / "lone" / "1.0")
    git(registry, "commit", "--quiet", "-am", "change lone")

    assert names(registry, changed_entries(registry, "main")) == ["lone"]


def test_a_new_recipe_that_is_not_committed_yet_counts(registry, names):
    publish(registry, "fresh", 'self.dep("zlib@1.0")')

    assert names(registry, changed_entries(registry, "main")) == ["fresh"]


def test_without_a_change_set_every_recipe_is_listed(registry, names):
    assert names(registry, None) == ["app", "gen", "lone", "png", "zlib"]


def test_a_recipe_that_refuses_a_profile_is_left_out_for_it(registry, names, windows_profile):
    publish(registry, "wayland", validate=LINUX_ONLY)

    assert "wayland" in names(registry, None)
    assert "wayland" not in names(registry, None, windows_profile)


def test_an_unknown_ref_is_reported(registry):
    with pytest.raises(SiloError, match="merge-base"):
        changed_entries(registry, "no-such-branch")
