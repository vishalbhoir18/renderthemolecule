import io
import json
import os
import shutil

import pytest
from PIL import Image

from app import about, cli
from app.errors import UserError


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


PNG_BYTES = _png()

BASE = ["--pdb-id", "4HHB", "--name", "Ada Lovelace", "--email", "Ada@Example.org"]


@pytest.fixture
def fake_pipeline(monkeypatch):
    calls = {}

    def fake_fetch(code, settings):
        calls["fetched"] = code
        path = settings.structures_dir / f"{code}.bcif"
        path.write_bytes(b"BCIF")
        return path

    def fake_render(request, structure, output, settings):
        calls["request"] = request
        output.write_bytes(PNG_BYTES)
        return {"atoms": 4779}

    monkeypatch.setattr(cli, "fetch_structure", fake_fetch)
    monkeypatch.setattr(cli, "run_blender", fake_render)
    return calls


def test_renders_and_writes_citation_and_sheet_row(tmp_path, fake_pipeline):
    out = tmp_path / "out"
    code = cli.main(BASE + ["--style", "surface", "--no-ligands", "--out", str(out)])
    assert code == 0
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] and (out / "4hhb_surface_default.png").exists()
    assert fake_pipeline["fetched"] == "4hhb"
    assert fake_pipeline["request"].style == "surface" and not fake_pipeline["request"].ligands
    assert result["legend"] == about.legend_sentence("4hhb")
    assert about.SITE_URL in result["references"][0]
    row = result["row"]
    assert (row["name"], row["email"], row["source"], row["status"]) == (
        "Ada Lovelace", "ada@example.org", "Colab", "done")
    assert row["link"].startswith(about.SITE_URL + "/?id=4HHB&style=surface")


def test_invalid_details_are_reported_without_rendering(tmp_path, fake_pipeline):
    out = tmp_path / "out"
    code = cli.main(["--pdb-id", "4HHB", "--name", "Ada", "--email", "nope", "--out", str(out)])
    assert code == 2
    result = json.loads((out / "result.json").read_text())
    assert result == {"ok": False, "error": "Please enter a valid email address, like name@university.edu."}
    assert "request" not in fake_pipeline


def test_failed_render_still_produces_a_sheet_row(tmp_path, fake_pipeline, monkeypatch):
    def not_found(code, settings):
        raise UserError("9ZZZ was not found in the Protein Data Bank.")

    monkeypatch.setattr(cli, "fetch_structure", not_found)
    out = tmp_path / "out"
    assert cli.main(["--pdb-id", "9zzz", "--name", "Ada", "--email", "a@b.org", "--out", str(out)]) == 2
    result = json.loads((out / "result.json").read_text())
    assert not result["ok"] and "not found" in result["error"]
    assert result["row"]["status"] == "failed" and result["row"]["source"] == "Colab"


def test_help_lists_every_option(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = capsys.readouterr().out
    for option in ("--style", "--color", "--material", "--viewpoint", "--resolution",
                   "--quality", "--background", "--ligands", "--assembly", "--credit"):
        assert option in text


def test_real_render_from_the_command_line(tmp_path):
    pytest.importorskip("molecularnodes")
    structure = os.environ.get("RTM_TEST_STRUCTURE")
    if not structure:
        pytest.skip("set RTM_TEST_STRUCTURE to a local .bcif file")
    local = tmp_path / "test.bcif"
    shutil.copy(structure, local)
    out = tmp_path / "out"
    args = BASE + ["--resolution", "800x800", "--quality", "draft", "--out", str(out),
                   "--structure-file", str(local)]
    assert cli.main(args) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] and result["atoms"] > 0
    assert os.path.getsize(result["image"]) > 10_000
