import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

VISITOR = {"name": "Ada Lovelace", "email": "ada@example.org"}


class FakeRecorder:
    def __init__(self):
        self.rows = []
        self.started = self.stopped = False

    def add(self, row):
        self.rows.append(row)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def recorder():
    return FakeRecorder()


@pytest.fixture
def client(settings, fake_renderer, recorder):
    with TestClient(create_app(settings, fake_renderer, recorder)) as c:
        yield c


def render(client, headers=None, **options):
    return client.post("/api/render", json={**VISITOR, **options}, headers=headers or {})


def poll(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_index_and_options(client):
    page = client.get("/")
    assert page.status_code == 200 and "Render the Molecule" in page.text
    assert 'id="email"' in page.text and 'id="name"' in page.text
    assert "developed by <strong>Vishal Bhoir</strong>" in page.text
    assert "https://orcid.org/0009-0004-8803-1967" in page.text and "GNU GPL v3" in page.text
    assert client.get("/static/app.js").status_code == 200
    opts = client.get("/api/options").json()
    assert {c["value"] for c in opts["choices"]["style"]} >= {"cartoon", "surface"}
    assert "name" not in opts["defaults"] and "email" not in opts["defaults"]


def test_render_round_trip(client):
    resp = render(client, pdb_id="4HHB", style="surface")
    assert resp.status_code == 202
    body = poll(client, resp.json()["id"])
    assert body["status"] == "done"
    assert body["download_name"] == "4hhb_surface_default.png"

    image = client.get(body["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]


@pytest.mark.parametrize(
    "visitor, message",
    [
        ({}, "Please enter your name."),
        ({"name": "Ada"}, "Please enter your email address."),
        ({"name": "  ", "email": "ada@example.org"}, "Please enter your name."),
        ({"name": "Ada", "email": "not-an-email"}, "valid email address"),
        ({"name": "=HYPERLINK(1)", "email": "ada@example.org"}, "cannot start with"),
    ],
)
def test_name_and_email_are_required(client, visitor, message):
    resp = client.post("/api/render", json={"pdb_id": "4hhb", **visitor})
    assert resp.status_code == 422
    assert message in resp.json()["error"]


def test_each_render_is_recorded_once_per_person(client, recorder, fake_renderer):
    fake_renderer.gate.clear()
    first = render(client, pdb_id="1EMA").json()
    # Someone else asks for the same picture while it renders: one job, two records.
    second = client.post(
        "/api/render", json={"pdb_id": "1ema", "name": "Grace Hopper", "email": "Grace@Example.org "}
    ).json()
    assert first["id"] == second["id"]
    fake_renderer.gate.set()
    poll(client, first["id"])
    # A later request is served from cache and recorded straight away.
    poll(client, render(client, pdb_id="1ema").json()["id"])

    deadline = time.time() + 5
    while len(recorder.rows) < 3 and time.time() < deadline:
        time.sleep(0.01)
    rows = recorder.rows
    assert [(r["name"], r["email"], r["cached"]) for r in rows] == [
        ("Ada Lovelace", "ada@example.org", "no"),
        ("Grace Hopper", "grace@example.org", "no"),
        ("Ada Lovelace", "ada@example.org", "yes"),
    ]
    assert rows[0]["pdb_id"] == "1EMA" and rows[0]["status"] == "done"
    assert rows[0]["link"].startswith("http://testserver/?id=1EMA&style=cartoon")
    assert "email" not in rows[0]["link"] and "Ada" not in rows[0]["link"]


def test_failed_render_is_recorded_with_error(client, recorder, fake_renderer, user_error_cls):
    fake_renderer.fail_with = user_error_cls("9ZZZ was not found")
    poll(client, render(client, pdb_id="9zzz").json()["id"])
    deadline = time.time() + 5
    while not recorder.rows and time.time() < deadline:
        time.sleep(0.01)
    assert recorder.rows[0]["status"] == "failed"
    assert recorder.rows[0]["error"] == "9ZZZ was not found"


def test_job_status_never_reveals_who_asked(client):
    job = render(client, pdb_id="4hhb").json()
    body = poll(client, job["id"])
    text = str(job) + str(body)
    assert "ada@example.org" not in text and "Ada" not in text


def test_public_url_from_proxy_headers(client, recorder):
    headers = {"x-forwarded-proto": "https", "host": "me-rtm.hf.space"}
    poll(client, render(client, headers=headers, pdb_id="1bna").json()["id"])
    deadline = time.time() + 5
    while not recorder.rows and time.time() < deadline:
        time.sleep(0.01)
    assert recorder.rows[0]["link"].startswith("https://me-rtm.hf.space/?id=1BNA")


def test_modal_addresses_always_use_https(client, recorder):
    poll(client, render(client, headers={"host": "vb--render-the-molecule.modal.run"}, pdb_id="1bna").json()["id"])
    deadline = time.time() + 5
    while not recorder.rows and time.time() < deadline:
        time.sleep(0.01)
    assert recorder.rows[0]["link"].startswith("https://vb--render-the-molecule.modal.run/?id=1BNA")


def test_cite_endpoint_uses_the_site_address(client):
    body = client.get("/api/cite", params={"pdb_id": "1EMA"}, headers={"host": "me-rtm.hf.space",
                                                                       "x-forwarded-proto": "https"}).json()
    assert body["credit"].startswith("PDB 1EMA")
    assert "PDB entry 1EMA" in body["legend"]
    assert "https://me-rtm.hf.space (source code: https://github.com/" in body["references"][0]
    assert len(body["references"]) == 5
    assert client.get("/api/cite", params={"pdb_id": "nope"}).status_code == 422


def test_invalid_pdb_id_gives_readable_message(client):
    resp = render(client, pdb_id="hello")
    assert resp.status_code == 422
    assert "not a valid PDB ID" in resp.json()["error"]


def test_invalid_option_names_the_field(client):
    resp = render(client, pdb_id="4hhb", quality="ultra")
    assert resp.status_code == 422
    assert resp.json()["error"].startswith("quality:")


def test_unknown_job_and_bad_render_names(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/renders/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/renders/" + "a" * 64 + ".png").status_code == 404


def test_rate_limit_uses_forwarded_client(client, fake_renderer):
    fake_renderer.gate.clear()
    headers = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    for code in ("1aaa", "1aab"):
        assert render(client, headers=headers, pdb_id=code).status_code == 202
    assert render(client, headers=headers, pdb_id="1aac").status_code == 429
    other = render(client, headers={"X-Forwarded-For": "198.51.100.2"}, pdb_id="1aac")
    assert other.status_code == 202
    fake_renderer.gate.set()


def test_recorder_lifecycle(settings, fake_renderer, recorder):
    with TestClient(create_app(settings, fake_renderer, recorder)):
        assert recorder.started
    assert recorder.stopped
