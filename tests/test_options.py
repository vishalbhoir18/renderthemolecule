import re

import pytest
from pydantic import ValidationError

from app.options import Camera, RenderRequest, Submission, option_lists


@pytest.mark.parametrize(
    "raw, expected",
    [("4HHB", "4hhb"), (" 1ema ", "1ema"), ("pdb_00004HHB", "pdb_00004hhb"), ("6vxx", "6vxx")],
)
def test_valid_pdb_ids_are_normalised(raw, expected):
    assert RenderRequest(pdb_id=raw).pdb_id == expected


@pytest.mark.parametrize(
    "raw",
    ["", "4hh", "4hhbb", "0abc", "../etc", "4hh;", "pdb_1234", "4h b", "abcd", 1234],
)
def test_invalid_pdb_ids_are_rejected(raw):
    with pytest.raises(ValidationError):
        RenderRequest(pdb_id=raw)


def test_unknown_options_are_rejected():
    with pytest.raises(ValidationError):
        RenderRequest(pdb_id="4hhb", style="wireframe")
    with pytest.raises(ValidationError):
        RenderRequest(pdb_id="4hhb", evil="x")


def test_cache_key_is_stable_and_option_sensitive():
    a = RenderRequest(pdb_id="4HHB")
    assert a.cache_key() == RenderRequest(pdb_id="4hhb").cache_key()
    assert a.cache_key() != RenderRequest(pdb_id="4hhb", style="surface").cache_key()
    assert len(a.cache_key()) == 64


def test_derived_values():
    r = RenderRequest(pdb_id="1ema", resolution="1920x1080", quality="draft")
    assert r.size == (1920, 1080)
    assert r.samples == 16
    assert r.download_name() == "1ema_cartoon_default.png"


def test_submission_cleans_name_and_email_and_keeps_them_out_of_the_cache_key():
    sub = Submission(pdb_id="4HHB", style="surface", name="  Marie   Curie ", email=" Marie@Sorbonne.FR ",
                     institution=" Sorbonne   University ", country="France")
    assert sub.name == "Marie Curie" and sub.email == "marie@sorbonne.fr"
    assert sub.institution == "Sorbonne University" and sub.country == "France"
    req = sub.render_request()
    assert type(req) is RenderRequest and req.style == "surface"
    assert sub.cache_key() == req.cache_key() == RenderRequest(pdb_id="4hhb", style="surface").cache_key()
    other = Submission(pdb_id="4hhb", style="surface", name="Someone Else", email="x@y.org",
                       institution="Elsewhere", country="India")
    assert other.cache_key() == sub.cache_key()


@pytest.mark.parametrize(
    "name, email",
    [
        ("", "a@b.org"),
        ("A" * 101, "a@b.org"),
        ("+Ada", "a@b.org"),
        ("Ada\x00", "a@b.org"),
        ("Ada", ""),
        ("Ada", "a@b"),
        ("Ada", "a b@c.org"),
        ("Ada", "=a@b.org"),
        ("Ada", "a@b.org" + "x" * 250),
    ],
)
def test_submission_rejects_bad_visitor_details(name, email):
    with pytest.raises(ValidationError):
        Submission(pdb_id="4hhb", name=name, email=email, institution="IISc", country="India")


@pytest.mark.parametrize(
    "institution, country",
    [("", "India"), ("IISc", ""), ("=SUM(1)", "India"), ("IISc", "+India"), ("I" * 201, "India"), ("IISc", "C" * 81)],
)
def test_submission_rejects_bad_institution_or_country(institution, country):
    with pytest.raises(ValidationError):
        Submission(pdb_id="4hhb", name="Ada", email="a@b.org", institution=institution, country=country)


def test_share_query_round_trips_through_the_form_names():
    req = RenderRequest(pdb_id="pdb_00004hhb", ligands=False, credit=False)
    assert req.share_query().startswith("id=PDB_00004HHB&style=cartoon")
    assert req.share_query().endswith("ligands=0&assembly=0&credit=0")


def test_option_lists_cover_every_choice_with_valid_defaults():
    data = option_lists()
    for field, choices in data["choices"].items():
        values = [c["value"] for c in choices]
        assert data["defaults"][field] in values
    assert data["defaults"]["ligands"] is True
    assert data["defaults"]["assembly"] is False
    # Chain colours shared by Blender and the 3D preview.
    colors = data["chain_colors"]
    assert len(colors) >= 6 and len(set(colors)) == len(colors)
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in colors)
    assert len(data["rainbow_colors"]) % 2 == 1  # an odd count: the middle of a chain hits a stop
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in [*data["rainbow_colors"], data["non_polymer_rainbow_color"]])


VIEW = {"position": [149.634, 50.82, 142.5701], "target": [105.44, -18.82, 186.16],
        "up": [0.64221, 0.0703, 0.7633], "fov": 45}


def test_camera_is_rounded_and_written_compactly():
    cam = Camera(**VIEW)
    assert cam.position == (149.63, 50.82, 142.57) and cam.up == (0.6422, 0.0703, 0.7633)
    assert cam.to_param() == "149.63,50.82,142.57,105.44,-18.82,186.16,0.6422,0.0703,0.7633,45"
    assert Camera.from_param(cam.to_param()) == cam
    assert Camera(position=[-0.001, 0, 10], target=[0, 0, 0], up=[0, 1, 0]).to_param() == "0,0,10,0,0,0,0,1,0,45"


def test_a_camera_replaces_the_viewpoint_and_changes_the_cache_key():
    plain = RenderRequest(pdb_id="1f2n", viewpoint="top")
    viewed = RenderRequest(pdb_id="1f2n", viewpoint="top", camera=VIEW)
    assert viewed.viewpoint == "default" and viewed.camera == Camera(**VIEW)
    # The text form from a link is the same view, so the same cached image.
    same = RenderRequest(pdb_id="1f2n", camera=Camera(**VIEW).to_param())
    assert viewed.cache_key() == same.cache_key() != plain.cache_key()
    moved = RenderRequest(pdb_id="1f2n", camera={**VIEW, "fov": 40})
    assert moved.cache_key() != viewed.cache_key()
    assert RenderRequest(pdb_id="1f2n", camera="").camera is None
    assert viewed.share_query().endswith("&cam=149.63%2C50.82%2C142.57%2C105.44%2C-18.82%2C186.16%2C0.6422%2C0.0703%2C0.7633%2C45")
    assert "cam=" not in plain.share_query()


def test_requests_without_a_camera_hash_only_their_options():
    import hashlib
    import json

    from app.options import RENDER_VERSION

    req = RenderRequest(pdb_id="4hhb")
    options = req.model_dump(exclude={"camera"})
    expected = hashlib.sha256(json.dumps({"v": RENDER_VERSION, **options}, sort_keys=True).encode()).hexdigest()
    assert req.cache_key() == expected


@pytest.mark.parametrize(
    "camera, message",
    [
        ("1,2,3", "10 numbers"),
        ("a,0,10,0,0,0,0,1,0,45", "10 numbers"),
        ({**VIEW, "position": [float("nan"), 0, 0]}, "within"),
        ({**VIEW, "target": [1e9, 0, 0]}, "within"),
        ({**VIEW, "position": VIEW["target"]}, "away from"),
        ({**VIEW, "up": [0, 0, 0]}, "non-zero"),
        ({"position": [0, 0, 10], "target": [0, 0, 0], "up": [0, 0, 1]}, "along its view"),
        ({**VIEW, "fov": 5}, "between 10 and 130"),
        ({**VIEW, "zoom": 2}, "Extra inputs"),
    ],
)
def test_bad_cameras_are_rejected(camera, message):
    with pytest.raises(ValidationError, match=message):
        RenderRequest(pdb_id="1f2n", camera=camera)
