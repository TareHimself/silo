import subprocess

import pytest

from silo.errors import SiloError
from silo.git_snapshot import fetch_commit, resolve_submodule_url
from silo.source import SourceSpec

COMMIT = "9f2c41d0a1b2c3d4e5f60718293a4b5c6d7e8f90"


def git(repo, *args: str) -> str:
    settings = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    # git refuses to clone a submodule from a local folder unless told the file protocol is fine
    settings += ["-c", "protocol.file.allow=always"]
    result = subprocess.run(
        ["git", *settings, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo(path, files: dict[str, str]):
    path.mkdir(parents=True)
    git(path, "init", "--quiet")
    for relative, text in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return path


def commit_all(repo) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "commit")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def parent_with_submodules(tmp_path):
    """engine -> third_party/fmt -> deps/core, plus engine -> third_party/docs."""
    core = make_repo(tmp_path / "core", {"core.c": "int core;\n"})
    commit_all(core)
    fmt = make_repo(tmp_path / "fmt", {"fmt.c": "int fmt;\n"})
    git(fmt, "submodule", "add", "--quiet", core.as_uri(), "deps/core")
    commit_all(fmt)
    docs = make_repo(tmp_path / "docs", {"manual.md": "manual\n"})
    commit_all(docs)

    engine = make_repo(tmp_path / "engine", {"engine.c": "int engine;\n"})
    git(engine, "submodule", "add", "--quiet", fmt.as_uri(), "third_party/fmt")
    git(engine, "submodule", "add", "--quiet", docs.as_uri(), "third_party/docs")
    return engine.as_uri(), commit_all(engine)


def test_submodules_are_not_fetched_unless_asked_for(parent_with_submodules, tmp_path):
    url, commit = parent_with_submodules

    fetch_commit(url, commit, tmp_path / "out")

    assert (tmp_path / "out" / "engine.c").is_file()
    assert not (tmp_path / "out" / "third_party" / "fmt" / "fmt.c").exists()


def test_all_submodules_are_fetched_recursively(parent_with_submodules, tmp_path):
    url, commit = parent_with_submodules

    fetch_commit(url, commit, tmp_path / "out", submodules=True)

    third_party = tmp_path / "out" / "third_party"
    assert (third_party / "fmt" / "fmt.c").read_text(encoding="utf-8") == "int fmt;\n"
    assert (third_party / "fmt" / "deps" / "core" / "core.c").is_file()
    assert (third_party / "docs" / "manual.md").is_file()
    assert not list((tmp_path / "out").rglob(".git"))
    assert not list((tmp_path / "out").rglob("*.index"))


def test_a_list_fetches_only_those_submodules_with_their_own(parent_with_submodules, tmp_path):
    url, commit = parent_with_submodules

    fetch_commit(url, commit, tmp_path / "out", submodules=["third_party/fmt"])

    third_party = tmp_path / "out" / "third_party"
    assert (third_party / "fmt" / "deps" / "core" / "core.c").is_file()
    assert not (third_party / "docs" / "manual.md").exists()


def test_naming_a_submodule_that_does_not_exist_is_an_error(parent_with_submodules, tmp_path):
    url, commit = parent_with_submodules

    with pytest.raises(SiloError, match=r"no submodule at third_party/nope.*third_party/fmt"):
        fetch_commit(url, commit, tmp_path / "out", submodules=["third_party/nope"])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/other/fmt.git", "https://example.com/other/fmt.git"),
        ("git@github.com:org/fmt.git", "git@github.com:org/fmt.git"),
        ("../fmt.git", "https://github.com/org/fmt.git"),
        ("../../other/fmt.git", "https://github.com/other/fmt.git"),
        ("./nested.git", "https://github.com/org/engine.git/nested.git"),
    ],
)
def test_relative_submodule_urls_resolve_against_the_parent(url, expected):
    assert resolve_submodule_url("https://github.com/org/engine.git", url) == expected


def test_the_submodule_choice_is_part_of_the_source_id():
    def source_id(**arguments) -> str:
        source = SourceSpec()
        source.git("https://example.com/lib.git", commit=COMMIT, **arguments)
        return source.id

    assert source_id() == f"fetched:{COMMIT}"
    assert source_id(submodules=True) == f"fetched:{COMMIT}+submodules:all"
    assert source_id(submodules=["b", "a"]) == f"fetched:{COMMIT}+submodules:a,b"
