import hashlib
import io
import urllib.error

import pytest

from silo import source
from silo.source import download

URL = "https://example.org/demo-1.0.tar.gz"
BODY = b"an archive"
SHA256 = hashlib.sha256(BODY).hexdigest()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "no", None, None)


@pytest.fixture
def server(monkeypatch):
    """Stands in for the network: each request takes the next answer of the list it returns."""
    answers = []
    asked = []

    def urlopen(request):
        asked.append(request.full_url)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer)

    monkeypatch.setattr(source.urllib.request, "urlopen", urlopen)
    return answers, asked


def test_a_download_that_fails_for_a_moment_is_tried_again(server):
    answers, asked = server
    answers += [http_error(418), ConnectionResetError("reset"), BODY]

    archive = download(URL, SHA256)

    assert archive.read_bytes() == BODY
    assert len(asked) == 3


def test_a_download_that_keeps_failing_gives_up_after_three_tries(server):
    answers, asked = server
    answers += [http_error(503)] * 4

    with pytest.raises(urllib.error.HTTPError):
        download(URL, SHA256)

    assert len(asked) == 3


def test_a_file_that_is_not_there_is_not_asked_for_twice(server):
    answers, asked = server
    answers += [http_error(404), BODY]

    with pytest.raises(urllib.error.HTTPError):
        download(URL, SHA256)

    assert len(asked) == 1
