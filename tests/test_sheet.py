import json
import re
import time
from pathlib import Path

import pytest
import requests

from app import sheet
from app.jobs import Job, Submitter
from app.options import RenderRequest

CODE_GS = Path(__file__).resolve().parent.parent / "google-sheet" / "Code.gs"


def js_array(name: str) -> list[str]:
    match = re.search(rf"const {name} = \[(.*?)\];", CODE_GS.read_text(), re.S)
    return json.loads("[" + match.group(1).strip().rstrip(",") + "]")


def test_columns_match_the_apps_script():
    assert js_array("KEYS") == sheet.ROW_KEYS
    assert len(js_array("HEADERS")) == len(sheet.ROW_KEYS)


def make_job(**changes) -> Job:
    req = RenderRequest(pdb_id="6vxx", style="surface", assembly=True)
    job = Job(req, req.cache_key(), "client", status="done", started_at=100.0, finished_at=121.26)
    for key, value in changes.items():
        setattr(job, key, value)
    return job


def test_record_row():
    submitter = Submitter("Ada", "ada@example.org", "https://x.hf.space", submitted_at=1_700_000_000.5)
    row = sheet.record_row(make_job(), submitter)
    assert list(row) == sheet.ROW_KEYS
    assert row["time"] == 1_700_000_000_500
    assert (row["name"], row["email"], row["pdb_id"]) == ("Ada", "ada@example.org", "6VXX")
    assert row["assembly"] == "yes" and row["cached"] == "no" and row["render_s"] == 21.3
    assert row["link"] == (
        "https://x.hf.space/?id=6VXX&style=surface&color=default&material=ambient_occlusion"
        "&viewpoint=default&resolution=1280x720&quality=standard&background=white"
        "&ligands=1&assembly=1"
    )
    cached = sheet.record_row(make_job(cached=True), submitter)
    assert cached["cached"] == "yes" and cached["render_s"] == ""


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


@pytest.fixture
def posts(monkeypatch):
    calls, answers = [], []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        answer = answers.pop(0) if answers else FakeResponse({"ok": True})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(sheet.requests, "post", fake_post)
    return calls, answers


def test_rows_are_sent_with_token(posts):
    calls, _ = posts
    rec = sheet.SheetRecorder("https://script.google.com/macros/s/abc/exec", "s3cret")
    rec.start()
    rec.add({"n": 1})
    rec.add({"n": 2})
    wait_for(lambda: sum(len(body["rows"]) for _, body in calls) == 2)
    rec.stop()
    url, body = calls[0]
    assert url.endswith("/exec") and body["token"] == "s3cret"
    assert [r["n"] for _, b in calls for r in b["rows"]] == [1, 2]


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("offline"),
        FakeResponse({}, status=500),
        FakeResponse({"ok": False, "error": "wrong token"}),
        FakeResponse(ValueError("html login page")),
    ],
)
def test_failed_sends_are_retried_in_order(posts, failure):
    calls, answers = posts
    answers.append(failure)
    rec = sheet.SheetRecorder("u", "t", retry_after=0.01)
    rec.add({"n": 1})
    rec.add({"n": 2})
    rec.start()
    wait_for(lambda: rec.pending() == 0 and len(calls) >= 2)
    rec.stop()
    assert [r["n"] for r in calls[-1][1]["rows"]] == [1, 2]


def test_pending_rows_are_capped(posts):
    rec = sheet.SheetRecorder("u", "t", max_pending=3)  # not started: nothing is sent
    for n in range(5):
        rec.add({"n": n})
    assert rec.pending() == 3
