import hashlib
import tarfile
import zipfile

import pytest

from silo import source
from silo.source import SourceSpec, fetch_source


def fetch(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(source, "download", lambda url, sha256: archive)
    spec = SourceSpec()
    spec.fetch(
        f"https://example.org/{archive.name}", hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    dest = tmp_path / "src"
    fetch_source(spec, dest)
    return dest


@pytest.mark.parametrize("kind", ["zip", "tar.gz"])
def test_an_archive_is_unpacked_without_its_single_top_folder(tmp_path, monkeypatch, kind):
    (tmp_path / "pkg-1.0").mkdir()
    (tmp_path / "pkg-1.0" / "README").write_text("hello")
    archive = tmp_path / f"pkg-1.0.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(tmp_path / "pkg-1.0" / "README", "pkg-1.0/README")
    else:
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(tmp_path / "pkg-1.0" / "README", "pkg-1.0/README")

    dest = fetch(tmp_path, monkeypatch, archive)

    assert (dest / "README").read_text() == "hello"
