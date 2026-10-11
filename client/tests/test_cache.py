import pytest
from typer.testing import CliRunner

from silo import cache, paths
from silo.cli import app
from silo.errors import SiloError
from silo.git_snapshot import checkout_tree, snapshot_tree


def write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_every_cache_lives_under_the_cache_folder_and_the_store_does_not():
    for entry in cache.CACHES:
        assert entry.directory().parent == paths.cache_dir()
    assert paths.cache_dir() not in paths.store_dir().parents


def test_clear_deletes_one_cache_and_reports_its_size():
    write(paths.downloads_dir() / "zlib.tar.gz", "12345")
    write(paths.builds_dir() / "zlib-abc" / "build" / "zlib.obj", "123")

    freed = cache.clear(cache.find_caches(["downloads"])[0])

    assert freed == 5
    assert not paths.downloads_dir().exists()
    assert cache.size_of(paths.builds_dir()) == 3


def test_clear_removes_read_only_files():
    locked = paths.git_sources_dir() / "repo" / "objects" / "ab" / "cdef"
    write(locked, "object")
    locked.chmod(0o444)

    cache.clear(cache.find_caches(["git"])[0])

    assert not paths.git_sources_dir().exists()


def test_no_names_means_every_cache():
    assert cache.find_caches([]) == list(cache.CACHES)


def test_an_unknown_cache_name_is_an_error():
    with pytest.raises(SiloError, match="No cache named store"):
        cache.find_caches(["store"])


def test_a_local_source_still_builds_after_its_snapshots_are_cleared(git_repo, tmp_path):
    write(git_repo / "same.c", "same")
    write(git_repo / "edited.c", "old")
    dest, index = tmp_path / "work", tmp_path / "work.index"
    checkout_tree(git_repo, snapshot_tree(git_repo), dest, index)

    cache.clear(cache.find_caches(["snapshots"])[0])
    write(git_repo / "edited.c", "new")
    checkout_tree(git_repo, snapshot_tree(git_repo), dest, index)

    assert (dest / "edited.c").read_text(encoding="utf-8") == "new"
    assert (dest / "same.c").read_text(encoding="utf-8") == "same"


def test_cli_lists_and_clears_caches():
    write(paths.downloads_dir() / "zlib.tar.gz", "12345")
    write(paths.store_dir() / "zlib-1.3.1-abc" / "silo" / "package.json", "{}")
    runner = CliRunner()

    listing = runner.invoke(app, ["cache", "list"])
    cleared = runner.invoke(app, ["cache", "clear"])
    unknown = runner.invoke(app, ["cache", "clear", "store"])

    assert "downloads" in listing.output and "5 B" in listing.output
    assert cleared.exit_code == 0
    assert not paths.cache_dir().exists() or not any(paths.cache_dir().iterdir())
    assert (paths.store_dir() / "zlib-1.3.1-abc").is_dir()
    assert unknown.exit_code == 1 and "No cache named store" in unknown.output
