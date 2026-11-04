import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import colab

FORM = dict(name=" Ada ", email="ada@example.org", pdb_id=" 4hhb ", style="surface", color="rainbow",
            material="flat", viewpoint="top", resolution="800x800", quality="draft",
            background="transparent", ligands=False, assembly=True, credit=True)


@pytest.mark.parametrize(
    "name, email, pdb_id, message",
    [("", "a@b.org", "4HHB", "name"), ("Ada", "nope", "4HHB", "email"), ("Ada", "a@b.org", " ", "PDB ID")],
)
def test_check_details(name, email, pdb_id, message):
    with pytest.raises(ValueError, match=message):
        colab.check_details(name, email, pdb_id)
    colab.check_details("Ada", "a@b.org", "4HHB")  # valid: no error


def test_cli_args_carry_every_choice():
    args = colab.cli_args(FORM, "/venv/bin/python", "/out")
    assert args[:3] == ["/venv/bin/python", "-m", "app.cli"]
    pairs = dict(zip(args[3::2], args[4::2]))
    assert pairs["--pdb-id"] == "4hhb" and pairs["--name"] == "Ada" and pairs["--out"] == "/out"
    assert pairs["--style"] == "surface" and pairs["--background"] == "transparent"
    assert "--no-ligands" in args and "--assembly" in args and "--credit" in args


FAKE_CLI = '''
import json, os, sys
args = sys.argv[1:]
out = args[args.index("--out") + 1]
print("Downloading 4HHB…", flush=True)
if os.environ.get("FAKE_CRASH"):
    sys.exit(1)
os.makedirs(out, exist_ok=True)
json.dump({"ok": True, "env": {k: os.environ.get(k) for k in ("MPLBACKEND", "PYTHONPATH")}},
          open(os.path.join(out, "result.json"), "w"))
print("Done.", flush=True)
'''


@pytest.fixture
def fake_repo(tmp_path):
    """A stand-in repository whose app.cli just reports what it was given."""
    (tmp_path / "repo" / "app").mkdir(parents=True)
    (tmp_path / "repo" / "app" / "__init__.py").write_text("")
    (tmp_path / "repo" / "app" / "cli.py").write_text(FAKE_CLI)
    return tmp_path / "repo"


def test_render_shows_messages_and_cleans_colabs_settings(fake_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MPLBACKEND", "module://matplotlib_inline.backend_inline")
    monkeypatch.setenv("PYTHONPATH", "/env/python")
    result = colab.render(FORM, python=sys.executable, repo_dir=str(fake_repo), out_dir=str(tmp_path / "out"))
    assert result["ok"]
    assert result["env"] == {"MPLBACKEND": "Agg", "PYTHONPATH": None}
    shown = capsys.readouterr().out
    assert "Downloading 4HHB…" in shown and "Done." in shown  # relayed into the notebook


def test_render_explains_a_crash(fake_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_CRASH", "1")
    result = colab.render(FORM, python=sys.executable, repo_dir=str(fake_repo), out_dir=str(tmp_path / "out"))
    assert not result["ok"] and "exit code 1" in result["error"]
    assert "Downloading 4HHB…" in capsys.readouterr().out


class FakeAppsScript(BaseHTTPRequestHandler):
    """Answers like Apps Script: POST -> 302 redirect -> GET returns the JSON reply."""

    received = []
    reply = {"ok": True, "added": 1}

    def do_POST(self):
        FakeAppsScript.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(302)
        self.send_header("Location", "/echo")
        self.end_headers()

    def do_GET(self):
        body = json.dumps(FakeAppsScript.reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def apps_script():
    server = HTTPServer(("127.0.0.1", 0), FakeAppsScript)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    FakeAppsScript.received.clear()
    FakeAppsScript.reply = {"ok": True, "added": 1}
    yield f"http://127.0.0.1:{server.server_port}/exec"
    server.shutdown()


def settings_file(tmp_path, url, key="colab-public"):
    path = tmp_path / "colab_recording.json"
    path.write_text(json.dumps({"url": url, "key": key}))
    return str(path)


def test_record_sends_the_row_with_the_colab_key(tmp_path, apps_script):
    result = {"ok": True, "row": {"name": "Ada", "pdb_id": "4HHB"}}
    assert colab.record(result, settings_file(tmp_path, apps_script)) == "Usage recorded."
    assert FakeAppsScript.received == [{"token": "colab-public", "rows": [{"name": "Ada", "pdb_id": "4HHB"}]}]


def test_record_reports_problems_without_failing(tmp_path, apps_script):
    result = {"ok": True, "row": {"name": "Ada"}}
    FakeAppsScript.reply = {"ok": False, "error": "wrong token"}
    assert colab.record(result, settings_file(tmp_path, apps_script)) == "Usage not recorded (wrong token)."
    assert colab.record({"ok": False, "error": "bad email"}, "x") == "Usage not recorded (no render was attempted)."
    assert colab.record(result, str(tmp_path / "missing.json")) == "Usage not recorded (no recording settings)."
    assert colab.record(result, settings_file(tmp_path, "", "")) == "Usage not recorded (recording is not set up)."
    closed = settings_file(tmp_path, "http://127.0.0.1:9/exec")
    assert colab.record(result, closed, timeout=2).startswith("Usage not recorded (")


def test_citation_markdown():
    text = colab.citation_markdown({"legend": "The structure of …", "references": ["A", "B"]})
    assert "### How to cite this image" in text and "1. A\n2. B" in text
