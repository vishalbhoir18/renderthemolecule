import pytest
from pydantic import ValidationError

from app.options import RenderRequest, Submission, option_lists


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
    sub = Submission(pdb_id="4HHB", style="surface", name="  Marie   Curie ", email=" Marie@Sorbonne.FR ")
    assert sub.name == "Marie Curie" and sub.email == "marie@sorbonne.fr"
    req = sub.render_request()
    assert type(req) is RenderRequest and req.style == "surface"
    assert sub.cache_key() == req.cache_key() == RenderRequest(pdb_id="4hhb", style="surface").cache_key()
    other = Submission(pdb_id="4hhb", style="surface", name="Someone Else", email="x@y.org")
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
        Submission(pdb_id="4hhb", name=name, email=email)


def test_share_query_round_trips_through_the_form_names():
    req = RenderRequest(pdb_id="pdb_00004hhb", ligands=False)
    assert req.share_query().startswith("id=PDB_00004HHB&style=cartoon")
    assert req.share_query().endswith("ligands=0&assembly=0")


def test_option_lists_cover_every_choice_with_valid_defaults():
    data = option_lists()
    for field, choices in data["choices"].items():
        values = [c["value"] for c in choices]
        assert data["defaults"][field] in values
    assert data["defaults"]["ligands"] is True
    assert data["defaults"]["assembly"] is False
