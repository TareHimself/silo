import hashlib
import tarfile

import pytest

from silo.builder import WorkDirs, prepare_source
from silo.dependency_graph import resolve
from silo.enums import BuildMode
from silo.errors import SiloError
from silo.source import SourceTree

GREETING_PATCH = b"""\
--- a/greeting.txt
+++ b/greeting.txt
@@ -1 +1 @@
-hello
+patched
"""

RECIPE = """\
from silo import SiloPackage


class Demo(SiloPackage):
    name = "demo"
    version = "1.0"

    def source(self, src):
        {source}

    def patch(self, src):
        src.apply("fix.patch")
        src.remove("bundled")
"""


def write(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read(path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def source_tree(tmp_path) -> SourceTree:
    write(tmp_path / "src" / "greeting.txt", b"hello\n")
    write(tmp_path / "recipe" / "fix.patch", GREETING_PATCH)
    return SourceTree(tmp_path / "src", tmp_path / "recipe")


def test_apply_patches_the_source_with_a_file_from_the_recipe(source_tree):
    source_tree.apply("fix.patch")

    assert read(source_tree.root / "greeting.txt") == "patched\n"


def test_a_patch_that_does_not_apply_is_an_error(source_tree):
    write(source_tree.root / "greeting.txt", b"something else\n")

    with pytest.raises(SiloError, match=r"fix\.patch does not apply"):
        source_tree.apply("fix.patch")


def test_a_missing_patch_file_is_an_error(source_tree):
    with pytest.raises(SiloError, match="Patch file not found"):
        source_tree.apply("nope.patch")


def test_remove_deletes_a_file_or_a_folder(source_tree):
    write(source_tree.root / "bundled" / "zlib" / "zlib.c", b"int z;")

    source_tree.remove("bundled")
    source_tree.remove("greeting.txt")

    assert list(source_tree.root.iterdir()) == []


def test_removing_something_that_is_not_there_is_an_error(source_tree):
    with pytest.raises(SiloError, match="Cannot remove 'bundled'"):
        source_tree.remove("bundled")


def prepared(recipe_dir, work_root) -> WorkDirs:
    node = resolve(recipe_dir, BuildMode.Release).nodes["demo"]
    dirs = WorkDirs(work_root)
    prepare_source(node, dirs)
    return dirs


def test_local_source_is_patched_in_the_work_copy_and_repatched_after_an_edit(git_repo, tmp_path):
    write(git_repo / "silopkg.py", RECIPE.format(source='src.local(".")').encode())
    write(git_repo / "fix.patch", GREETING_PATCH)
    write(git_repo / "greeting.txt", b"hello\n")
    write(git_repo / "other.txt", b"one\n")
    write(git_repo / "bundled" / "zlib.c", b"int z;")

    dirs = prepared(git_repo, tmp_path / "work")

    assert read(dirs.source / "greeting.txt") == "patched\n"
    assert not (dirs.source / "bundled").exists()
    assert read(git_repo / "greeting.txt") == "hello\n"
    assert (git_repo / "bundled" / "zlib.c").exists()

    write(git_repo / "other.txt", b"two\n")
    dirs = prepared(git_repo, tmp_path / "work")

    assert read(dirs.source / "other.txt") == "two\n"
    assert read(dirs.source / "greeting.txt") == "patched\n"
    assert not (dirs.source / "bundled").exists()


def test_local_source_is_left_alone_when_nothing_changed(git_repo, tmp_path):
    write(git_repo / "silopkg.py", RECIPE.format(source='src.local(".")').encode())
    write(git_repo / "fix.patch", GREETING_PATCH)
    write(git_repo / "greeting.txt", b"hello\n")
    write(git_repo / "bundled" / "zlib.c", b"int z;")
    dirs = prepared(git_repo, tmp_path / "work")
    patched_at = (dirs.source / "greeting.txt").stat().st_mtime_ns

    dirs = prepared(git_repo, tmp_path / "work")

    assert (dirs.source / "greeting.txt").stat().st_mtime_ns == patched_at


def test_fetched_source_is_patched_once_after_unpacking(tmp_path):
    upstream = tmp_path / "upstream" / "demo-1.0"
    write(upstream / "greeting.txt", b"hello\n")
    write(upstream / "bundled" / "zlib.c", b"int z;")
    archive = tmp_path / "demo-1.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(upstream, arcname="demo-1.0")
    sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()

    recipe_dir = tmp_path / "recipe"
    fetch = f'src.fetch("{archive.as_uri()}", sha256="{sha256}")'
    write(recipe_dir / "silopkg.py", RECIPE.format(source=fetch).encode())
    write(recipe_dir / "fix.patch", GREETING_PATCH)

    dirs = prepared(recipe_dir, tmp_path / "work")
    assert read(dirs.source / "greeting.txt") == "patched\n"
    assert not (dirs.source / "bundled").exists()

    prepared(recipe_dir, tmp_path / "work")
    assert read(dirs.source / "greeting.txt") == "patched\n"


def test_replace_swaps_text_in_a_file(source_tree):
    source_tree.replace("greeting.txt", "hello", "goodbye")

    assert read(source_tree.root / "greeting.txt") == "goodbye\n"


def test_replacing_text_that_is_not_there_is_an_error(source_tree):
    with pytest.raises(SiloError, match="does not contain 'bonjour'"):
        source_tree.replace("greeting.txt", "bonjour", "goodbye")


def test_replacing_in_a_missing_file_is_an_error(source_tree):
    with pytest.raises(SiloError, match=r"Cannot edit 'nope.txt'"):
        source_tree.replace("nope.txt", "hello", "goodbye")
