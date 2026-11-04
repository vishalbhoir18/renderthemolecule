import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(settings, fake_renderer):
    with TestClient(create_app(settings, fake_renderer)) as c:
        yield c


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
    assert client.get("/static/app.js").status_code == 200
    opts = client.get("/api/options").json()
    assert {c["value"] for c in opts["choices"]["style"]} >= {"cartoon", "surface"}


def test_render_round_trip(client):
    resp = client.post("/api/render", json={"pdb_id": "4HHB", "style": "surface"})
    assert resp.status_code == 202
    body = poll(client, resp.json()["id"])
    assert body["status"] == "done"
    assert body["download_name"] == "4hhb_surface_default.png"

    image = client.get(body["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]


def test_invalid_pdb_id_gives_readable_message(client):
    resp = client.post("/api/render", json={"pdb_id": "hello"})
    assert resp.status_code == 422
    assert "not a valid PDB ID" in resp.json()["error"]


def test_invalid_option_names_the_field(client):
    resp = client.post("/api/render", json={"pdb_id": "4hhb", "quality": "ultra"})
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
        assert client.post("/api/render", json={"pdb_id": code}, headers=headers).status_code == 202
    resp = client.post("/api/render", json={"pdb_id": "1aac"}, headers=headers)
    assert resp.status_code == 429
    other = client.post("/api/render", json={"pdb_id": "1aac"}, headers={"X-Forwarded-For": "198.51.100.2"})
    assert other.status_code == 202
    fake_renderer.gate.set()
