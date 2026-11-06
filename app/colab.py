"""Helpers for the Google Colab notebook (notebooks/render_the_molecule.ipynb).

This module runs in Colab's own Python, so it uses only the standard library.
Rendering runs in a separate environment that has Blender (via app.cli).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

CHOICE_FIELDS = ("style", "color", "material", "viewpoint", "resolution", "quality", "background")
SWITCH_FIELDS = ("ligands", "assembly", "credit")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_details(form: dict) -> None:
    """Quick check of the form before the long install; the CLI checks everything."""
    if not form["name"].strip():
        raise ValueError("Please enter your name in the form.")
    if not EMAIL_RE.fullmatch(form["email"].strip()):
        raise ValueError("Please enter a valid email address in the form, like name@university.edu.")
    if not form["institution"].strip():
        raise ValueError("Please enter your institution in the form.")
    if not form["country"].strip():
        raise ValueError("Please enter your country in the form.")
    if not form["pdb_id"].strip():
        raise ValueError("Please enter a PDB ID in the form, for example 4HHB.")


def cli_args(form: dict, python: str, out_dir: str) -> list[str]:
    args = [python, "-m", "app.cli",
            "--pdb-id", form["pdb_id"].strip(), "--name", form["name"].strip(),
            "--email", form["email"].strip(), "--institution", form["institution"].strip(),
            "--country", form["country"].strip(), "--out", out_dir]
    for field in CHOICE_FIELDS:
        args += [f"--{field}", str(form[field])]
    for field in SWITCH_FIELDS:
        args.append(f"--{field}" if form[field] else f"--no-{field}")
    return args


def renderer_environment() -> dict[str, str]:
    """Colab's environment, minus what belongs to Colab's own Python.

    Colab sets PYTHONPATH and MPLBACKEND for its notebook; the renderer runs in a
    separate Python where those point at things that do not exist.
    """
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def render(form: dict, *, python: str, repo_dir: str, out_dir: str, extra_args: list[str] = ()) -> dict:
    """Run the renderer and show its messages in the notebook. Returns result.json."""
    result_path = Path(out_dir) / "result.json"
    result_path.unlink(missing_ok=True)
    # Colab does not show output written directly by child processes, so relay it.
    proc = subprocess.Popen(
        cli_args(form, python, out_dir) + list(extra_args), cwd=repo_dir, env=renderer_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(line.rstrip("\n"), flush=True)
    proc.wait()
    if not result_path.exists():
        return {"ok": False, "error": f"The renderer stopped unexpectedly (exit code {proc.returncode}); "
                                      "see the messages above."}
    return json.loads(result_path.read_text())


def record(result: dict, settings_file: str, timeout: float = 30) -> str:
    """Add this render to the site owner's Google Sheet; returns a short status line."""
    row = result.get("row")
    if not row:
        return "Usage not recorded (no render was attempted)."
    try:
        settings = json.loads(Path(settings_file).read_text())
    except (OSError, ValueError):
        return "Usage not recorded (no recording settings)."
    url, key = settings.get("url", "").strip(), settings.get("key", "").strip()
    if not (url and key):
        return "Usage not recorded (recording is not set up)."
    body = json.dumps({"token": key, "rows": [row]}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        # Apps Script answers with a redirect to the result, which urllib follows.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.loads(response.read().decode() or "{}")
    except Exception as exc:  # network trouble must never spoil the image
        return f"Usage not recorded ({type(exc).__name__})."
    return "Usage recorded." if reply.get("ok") else f"Usage not recorded ({reply.get('error', 'unknown error')})."


def citation_markdown(result: dict) -> str:
    refs = "\n".join(f"{i}. {text}" for i, text in enumerate(result["references"], start=1))
    return (
        "### How to cite this image\n\n"
        f"**For the figure legend or methods:** {result['legend']}\n\n"
        f"**References**\n\n{refs}\n"
    )
