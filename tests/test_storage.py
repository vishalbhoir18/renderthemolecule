import gzip
import os
import time

import pytest
import requests

from app import storage
from app.errors import UserError


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status_code = status
        self._body = body

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_get(response=None, raises=None, calls=None):
    def get(url, **kwargs):
        if calls is not None:
            calls.append(url)
        if raises:
            raise raises
        return response

    return get


def test_downloads_once_then_uses_cache(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(storage.requests, "get", fake_get(FakeResponse(body=b"BCIF"), calls=calls))
    first = storage.fetch_structure("4hhb", settings)
    second = storage.fetch_structure("4hhb", settings)
    assert first == second and first.read_bytes() == b"BCIF"
    assert calls == ["https://models.rcsb.org/4hhb.bcif"]


def test_gzipped_download_is_unpacked(settings, monkeypatch):
    monkeypatch.setattr(storage.requests, "get", fake_get(FakeResponse(body=gzip.compress(b"DATA"))))
    assert storage.fetch_structure("1ema", settings).read_bytes() == b"DATA"


@pytest.mark.parametrize(
    "response, raises, message",
    [
        (FakeResponse(404), None, "not found"),
        (FakeResponse(503), None, "HTTP 503"),
        (None, requests.ConnectionError("boom"), "Could not reach"),
    ],
)
def test_download_errors_are_user_facing(settings, monkeypatch, response, raises, message):
    monkeypatch.setattr(storage.requests, "get", fake_get(response, raises))
    with pytest.raises(UserError, match=message):
        storage.fetch_structure("9xyz", settings)
    assert not (settings.structures_dir / "9xyz.bcif").exists()


def test_oversized_download_is_refused(settings, monkeypatch):
    small = settings.__class__(data_dir=settings.data_dir, max_download_mb=1)
    big = FakeResponse(body=b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(storage.requests, "get", fake_get(big))
    with pytest.raises(UserError, match="larger than 1 MB"):
        storage.fetch_structure("1big", small)


def test_prune_removes_oldest_first(tmp_path):
    now = time.time()
    for i, name in enumerate(["old", "mid", "new"]):
        path = tmp_path / name
        path.write_bytes(b"x" * 600_000)
        os.utime(path, (now - 100 + i, now - 100 + i))
    storage.prune_directory(tmp_path, max_mb=1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["new"]
