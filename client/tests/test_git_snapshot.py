import subprocess

import pytest

from silo.errors import SiloError
from silo.git_snapshot import checkout_tree, snapshot_tree


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git_status(repo) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def test_snapshot_changes_with_uncommitted_and_untracked_edits(git_repo):
    write(git_repo / "a.txt", "one")
    first = snapshot_tree(git_repo)
    assert snapshot_tree(git_repo) == first

    write(git_repo / "a.txt", "two")
    second = snapshot_tree(git_repo)
    write(git_repo / "new.txt", "untracked")

    assert len({first, second, snapshot_tree(git_repo)}) == 3


def test_snapshot_ignores_what_gitignore_ignores(git_repo):
    write(git_repo / ".gitignore", "build/\n")
    write(git_repo / "a.txt", "one")
    before = snapshot_tree(git_repo)

    write(git_repo / "build" / "output.obj", "junk")

    assert snapshot_tree(git_repo) == before


def test_snapshot_of_a_subfolder_only_sees_that_subfolder(git_repo):
    write(git_repo / "libs" / "foo" / "foo.c", "int foo;")
    write(git_repo / "other.txt", "one")
    before = snapshot_tree(git_repo / "libs" / "foo")

    write(git_repo / "other.txt", "two")

    assert snapshot_tree(git_repo / "libs" / "foo") == before


def test_snapshot_leaves_the_users_repo_untouched(git_repo):
    write(git_repo / "a.txt", "one")
    status_before = git_status(git_repo)
    index = git_repo / ".git" / "index"
    assert not index.exists()

    snapshot_tree(git_repo)

    assert git_status(git_repo) == status_before == "?? a.txt\n"
    assert not index.exists()
    assert not any((git_repo / ".git" / "objects").glob("??/*"))


def test_snapshot_outside_a_repository_is_an_error(tmp_path):
    with pytest.raises(SiloError, match="must be inside a git repository"):
        snapshot_tree(tmp_path)


def test_checkout_copies_the_snapshot(git_repo, tmp_path):
    write(git_repo / "src" / "main.c", "int main;")
    dest = tmp_path / "work"

    checkout_tree(git_repo, snapshot_tree(git_repo), dest, tmp_path / "work.index")

    assert (dest / "src" / "main.c").read_text(encoding="utf-8") == "int main;"


def test_checkout_rewrites_only_what_changed_and_undoes_patches(git_repo, tmp_path):
    write(git_repo / "same.c", "same")
    write(git_repo / "edited.c", "old")
    write(git_repo / "patched.c", "original")
    write(git_repo / "removed.c", "gone soon")
    dest, index = tmp_path / "work", tmp_path / "work.index"
    checkout_tree(git_repo, snapshot_tree(git_repo), dest, index)
    untouched_mtime = (dest / "same.c").stat().st_mtime_ns

    write(dest / "patched.c", "changed by a recipe's patch()")
    write(git_repo / "edited.c", "new")
    (git_repo / "removed.c").unlink()
    checkout_tree(git_repo, snapshot_tree(git_repo), dest, index)

    assert (dest / "edited.c").read_text(encoding="utf-8") == "new"
    assert (dest / "patched.c").read_text(encoding="utf-8") == "original"
    assert not (dest / "removed.c").exists()
    assert (dest / "same.c").stat().st_mtime_ns == untouched_mtime
