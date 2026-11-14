import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.errors import UserError
from app.main import create_app
from app.options import Camera

VISITOR = {"name": "Ada Lovelace", "email": "ada@example.org", "institution": "University of London",
           "country": "United Kingdom"}


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


VIEW = {"position": [149.63, 50.82, 142.57], "target": [105.44, -18.82, 186.16], "up": [0.6422, 0.0703, 0.7633], "fov": 45}


def test_render_this_view(client, recorder, fake_renderer):
    body = poll(client, render(client, pdb_id="1F2N", viewpoint="top", camera=VIEW).json()["id"])
    assert body["status"] == "done"
    assert fake_renderer.calls[-1].camera == Camera(**VIEW)
    assert fake_renderer.calls[-1].viewpoint == "default"  # the camera replaces the preset
    deadline = time.time() + 5
    while not recorder.rows and time.time() < deadline:
        time.sleep(0.01)
    assert recorder.rows[0]["viewpoint"] == "3D preview"
    assert "&cam=149.63%2C50.82" in recorder.rows[0]["link"]
    # The same view again, as text from a shared link, is served from the cache.
    again = poll(client, render(client, pdb_id="1f2n", camera=Camera(**VIEW).to_param()).json()["id"])
    assert again["cached"] and len(fake_renderer.calls) == 1


def test_bad_camera_names_the_field(client):
    resp = render(client, pdb_id="1f2n", camera={**VIEW, "fov": 300})
    assert resp.status_code == 422
    assert resp.json()["error"].startswith("camera.fov: the field of view must be between 10 and 130")


def test_structure_for_the_preview(client, settings, monkeypatch):
    (settings.structures_dir / "1f2n.bcif").write_bytes(b"BCIF" * 1000)
    resp = client.get("/api/structure/1F2N")
    assert resp.status_code == 200 and resp.content == b"BCIF" * 1000
    assert resp.headers["content-encoding"] == "gzip"  # bcif shrinks a lot

    def missing(code, settings):
        raise UserError(f"{code.upper()} was not found in the Protein Data Bank.")

    monkeypatch.setattr(main, "fetch_structure", missing)
    resp = client.get("/api/structure/9zzz")
    assert resp.status_code == 404 and "9ZZZ was not found" in resp.json()["error"]
    assert client.get("/api/structure/hello").status_code == 422


def test_preview_files_are_served_compressed(client):
    page = client.get("/").text
    assert '<script src="/static/preview.js"></script>' in page and 'id="use_view"' in page
    assert client.get("/static/preview.js").status_code == 200
    # The preset framing is loaded before the preview that uses it.
    assert page.index('src="/static/framing.js"') < page.index('src="/static/preview.js"')
    assert client.get("/static/framing.js").status_code == 200
    viewer = client.get("/static/vendor/molstar/molstar.js")
    assert viewer.status_code == 200 and viewer.headers["content-encoding"] == "gzip"
    assert "MIT License" in client.get("/static/vendor/molstar/LICENSE").text
    assert "/static/vendor/molstar/molstar.js" in client.get("/static/preview.js").text


def test_index_and_options(client):
    page = client.get("/")
    assert page.status_code == 200 and "Render the Molecule" in page.text
    for field in ("name", "email", "institution", "country"):
        assert f'id="{field}"' in page.text
    assert 'href="/privacy"' in page.text
    assert 'Render the Molecule <span class="byline">by <a href="https://linktr.ee/thebioway"' in page.text
    assert 'Render the Molecule App developed by <a href="https://linktr.ee/thebioway"' in page.text
    # The footer links the author's ORCID (app/about.py), after the name.
    from app import about
    orcid = about.AUTHOR_ORCID
    assert f'(<a href="{orcid}" target="_blank" rel="noopener">{orcid}</a>)' in page.text
    # "Save preview image", with the Mol* citation next to it.
    assert 'id="save-preview"' in page.text and "https://doi.org/10.1093/nar/gkab314" in page.text
    assert client.get("/static/app.js").status_code == 200
    opts = client.get("/api/options").json()
    assert {c["value"] for c in opts["choices"]["style"]} >= {"cartoon", "surface"}
    assert not {"name", "email", "institution", "country"} & set(opts["defaults"])


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
    assert "content-encoding" not in image.headers  # PNGs are already compressed


@pytest.mark.parametrize(
    "visitor, message",
    [
        ({}, "Please enter your name."),
        ({"name": "Ada"}, "Please enter your email address."),
        ({**VISITOR, "name": "  "}, "Please enter your name."),
        ({**VISITOR, "email": "not-an-email"}, "valid email address"),
        ({**VISITOR, "name": "=HYPERLINK(1)"}, "cannot start with"),
        ({"name": "Ada", "email": "a@b.org"}, "Please enter your institution."),
        ({**VISITOR, "institution": ""}, "Please enter your institution."),
        ({**VISITOR, "country": " "}, "Please enter your country."),
        ({**VISITOR, "country": "@home"}, "Your country cannot start with"),
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
        "/api/render", json={"pdb_id": "1ema", "name": "Grace Hopper", "email": "Grace@Example.org ",
                             "institution": "Yale University", "country": "United States"}
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
    assert [(r["name"], r["email"], r["institution"], r["country"], r["cached"]) for r in rows] == [
        ("Ada Lovelace", "ada@example.org", "University of London", "United Kingdom", "no"),
        ("Grace Hopper", "grace@example.org", "Yale University", "United States", "no"),
        ("Ada Lovelace", "ada@example.org", "University of London", "United Kingdom", "yes"),
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
    for detail in VISITOR.values():
        assert detail not in text


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
    assert body["references"][0].endswith(
        "Zenodo. https://doi.org/10.5281/zenodo.23960655 (web application: https://me-rtm.hf.space)"
    )
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


def test_privacy_notice_is_served(client):
    page = client.get("/privacy")
    assert page.status_code == 200
    assert "understand academic adoption and improve the application" in page.text
    assert "not be shared or used for marketing without your separate consent" in page.text
