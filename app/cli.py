"""Render one image from the command line, with the same pipeline as the web app.

Used by the Google Colab notebook, and handy on any Linux x86-64 machine:

    python -m app.cli --pdb-id 4HHB --name "Ada Lovelace" --email ada@example.org \
        --institution "University of London" --country "United Kingdom" --out results

Every option of the web form is available (see --help). Writes the PNG and a
result.json into --out. result.json holds the citation text and the row for
the Google Sheet record; on failure it holds {"ok": false, "error": "..."}.
Exit codes: 0 rendered, 2 the request or the structure was rejected, 1 crash.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from pydantic import ValidationError

from . import about
from .config import Settings
from .errors import UserError
from .jobs import Job, Submitter
from .options import LABELS, RenderRequest, Submission
from .renderer import run_blender
from .sheet import record_row
from .storage import fetch_structure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Render a PDB entry with Blender + Molecular Nodes (Render the Molecule).",
    )
    parser.add_argument("--pdb-id", required=True, help="PDB ID, for example 4HHB")
    parser.add_argument("--name", required=True, help="your name (recorded with the render)")
    parser.add_argument("--email", required=True, help="your email (recorded with the render)")
    parser.add_argument("--institution", required=True, help="your institution (recorded with the render)")
    parser.add_argument("--country", required=True, help="your country (recorded with the render)")
    defaults = RenderRequest.model_fields
    for field in ("style", "color", "material", "viewpoint", "resolution", "quality", "background"):
        parser.add_argument(
            f"--{field}", choices=list(LABELS[field]), default=defaults[field].default
        )
    for field in ("ligands", "assembly", "credit"):
        parser.add_argument(
            f"--{field}", action=argparse.BooleanOptionalAction, default=defaults[field].default
        )
    parser.add_argument("--out", type=Path, default=Path("render-output"), help="output folder")
    parser.add_argument("--source", default="Colab", help="value of the Sheet's Source column")
    parser.add_argument(
        "--structure-file", type=Path,
        help="render this local .bcif file instead of downloading the PDB entry",
    )
    return parser


def _error(out: Path, message: str) -> int:
    (out / "result.json").write_text(json.dumps({"ok": False, "error": message}, indent=2))
    print(f"Error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out: Path = args.out.absolute()
    out.mkdir(parents=True, exist_ok=True)

    fields = {name: getattr(args, name) for name in Submission.model_fields}
    try:
        submission = Submission(**fields)
    except ValidationError as exc:
        return _error(out, str(exc.errors()[0]["msg"]).removeprefix("Value error, "))
    request = submission.render_request()
    submitter = Submitter(
        submission.name, submission.email, base_url=about.SITE_URL,
        institution=submission.institution, country=submission.country,
    )

    settings = Settings(data_dir=out / ".cache")
    settings.ensure_dirs()
    job = Job(request, request.cache_key(), client="cli", status="running", started_at=time.time())
    image = out / request.download_name()
    try:
        if args.structure_file:
            structure = args.structure_file.absolute()
        else:
            print(f"Downloading {request.pdb_id.upper()} from the Protein Data Bank…", flush=True)
            structure = fetch_structure(request.pdb_id, settings)
        print("Rendering with Blender (about 30–120 s)…", flush=True)
        info = run_blender(request, structure, image, settings)
    except UserError as exc:
        job.status, job.error, job.finished_at = "failed", str(exc), time.time()
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # crash: still write result.json so the caller can explain it
        traceback.print_exc()
        message = f"Rendering failed ({type(exc).__name__}): {exc}"
        job.status, job.error, job.finished_at = "failed", message.splitlines()[0], time.time()
        result = {"ok": False, "error": message}
    else:
        job.status, job.finished_at = "done", time.time()
        result = {
            "ok": True,
            "image": str(image),
            "render_s": round(job.finished_at - job.started_at, 1),
            "atoms": info.get("atoms"),
            "legend": about.legend_sentence(request.pdb_id),
            "references": about.references(request.pdb_id, about.SITE_URL),
        }
    row = record_row(job, submitter)
    row["source"] = args.source
    result["row"] = row
    (out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 2
    print(f"Done in {result['render_s']} s: {image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
