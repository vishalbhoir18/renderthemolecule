"""Turn a RenderRequest into a PNG: download the structure, then run Blender."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .errors import UserError
from .options import RenderRequest
from .storage import fetch_structure

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (request, output_path, set_stage) -> None; raises UserError for visitor-facing failures.
RenderFn = Callable[[RenderRequest, Path, Callable[[str], None]], None]


def make_renderer(settings: Settings) -> RenderFn:
    def render(request: RenderRequest, output: Path, set_stage: Callable[[str], None]) -> None:
        set_stage("downloading")
        structure = fetch_structure(request.pdb_id, settings)
        set_stage("rendering")
        run_blender(request, structure, output, settings)

    return render


def run_blender(
    request: RenderRequest, structure: Path, output: Path, settings: Settings
) -> dict:
    """Render in a separate Python process; returns its result info."""
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.work_dir) as tmp:
        tmp_dir = Path(tmp)
        tmp_png = tmp_dir / "render.png"
        spec = {
            **request.model_dump(),
            "size": list(request.size),
            "samples": request.samples,
            "structure_path": str(structure),
            "output_path": str(tmp_png),
            "max_atoms": settings.max_atoms(request.style),
            "threads": settings.threads(),
        }
        spec_path = tmp_dir / "spec.json"
        spec_path.write_text(json.dumps(spec))
        log_path = tmp_dir / "blender.log"

        with open(log_path, "w") as log_file:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "app.blender_render", str(spec_path)],
                    cwd=PROJECT_ROOT,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    timeout=settings.render_timeout,
                    env={**os.environ, "PYTHONWARNINGS": "ignore"},
                )
            except subprocess.TimeoutExpired as exc:
                raise UserError(
                    f"Rendering took longer than {settings.render_timeout} seconds and "
                    "was stopped. Try Draft quality, a smaller image or the Cartoon style."
                ) from exc

        result_path = tmp_dir / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        if result is not None and not result.get("ok"):
            raise UserError(result.get("error") or "Rendering failed.")
        if proc.returncode != 0 or not tmp_png.exists():
            tail = log_path.read_text(errors="replace").splitlines()[-40:]
            log.error(
                "render of %s failed (exit %s):\n%s",
                request.pdb_id,
                proc.returncode,
                "\n".join(tail),
            )
            raise RuntimeError(f"Blender exited with code {proc.returncode}")

        os.replace(tmp_png, output)
        log.info("rendered %s %s", request.pdb_id, result)
        return result or {}
