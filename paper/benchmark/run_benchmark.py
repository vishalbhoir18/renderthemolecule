"""Benchmark Render the Molecule on a panel of PDB entries.

Every render goes through the app's own code: the structure is downloaded by
app.storage.fetch_structure and rendered by `python -m app.blender_render`
in a fresh process, exactly as app.renderer.run_blender does. This script only
adds timing and memory measurement (os.wait4 gives the peak resident memory of
each render process).

    python paper/benchmark/run_benchmark.py            # all experiments
    python paper/benchmark/run_benchmark.py E1 E3      # selected experiments

Results are appended to paper/benchmark/results.csv; images go to
paper/benchmark/renders/. Re-running skips rows already in the CSV.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.options import RenderRequest  # noqa: E402
from app.renderer import blender_environment  # noqa: E402
from app.storage import fetch_structure  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "renders"
CSV_PATH = HERE / "results.csv"
SETTINGS = Settings(data_dir=HERE / ".cache", render_timeout=1800)

# Ten entries from 327 to 2.44 million deposited atoms.
PANEL = ["1crn", "1bna", "1ubq", "1ehz", "4hhb", "1cd3", "6vxx", "1aon", "4ug0", "3j3q"]

FIELDS = [
    "experiment", "run_id", "pdb_id", "style", "color", "material", "quality", "samples",
    "resolution", "assembly", "threads", "status", "atoms_rendered", "setup_s", "render_s",
    "wall_s", "peak_rss_mb", "png_kb", "error", "image",
]


def experiments() -> dict[str, list[dict]]:
    e = {}
    # E1: scaling with structure size, three representative styles.
    e["E1"] = [
        {"pdb_id": p, "style": s}
        for p in PANEL
        for s in ("cartoon", "surface", "spheres")
    ]
    # E2: every style and colour scheme on haemoglobin (also the figure panels).
    e["E2"] = [{"pdb_id": "4hhb", "style": s} for s in
               ("cartoon", "ribbon", "surface", "spheres", "ball_and_stick", "sticks")]
    e["E2"] += [{"pdb_id": "4hhb", "style": st, "color": c}
                for st in ("cartoon", "surface")
                for c in ("rainbow", "secondary_structure", "goodsell")]
    # E3: sampling presets against a high-sample reference (image quality).
    e["E3"] = [{"pdb_id": p, "style": s, "quality": q}
               for p, s in (("4hhb", "cartoon"), ("1aon", "surface"))
               for q in ("draft", "standard", "high")]
    e["E3"] += [{"pdb_id": p, "style": s, "samples": 512, "tag": "ref"}
                for p, s in (("4hhb", "cartoon"), ("1aon", "surface"))]
    # E4: CPU threads.
    e["E4"] = [{"pdb_id": "4hhb", "style": "cartoon", "threads": t} for t in (1, 2, 4)]
    # E5: biological assembly (60-copy phiX174 procapsid).
    e["E5"] = [{"pdb_id": "1cd3", "style": s, "assembly": a}
               for s in ("cartoon", "surface") for a in (False, True)]
    # E6: repeatability: identical requests rendered twice.
    e["E6"] = [{"pdb_id": "4hhb", "style": "cartoon", "tag": f"rep{i}"} for i in (1, 2)]
    # E8: the Mol* preview against the render (paper/benchmark/capture_previews.js):
    # each entry in its preset view (no camera sent) and in a turned view (camera sent).
    cams_path = HERE / "preview" / "cameras.json"
    cams = json.loads(cams_path.read_text()) if cams_path.exists() else {}
    e["E8"] = []
    for key, cam in sorted(cams.items()):
        pdb, view = key.split("_")
        cfg = {"pdb_id": pdb.lower(), "style": "cartoon", "credit": False, "tag": view}
        if view == "moved":
            cfg["camera"] = cam
        e["E8"].append(cfg)
    # E7: output resolution.
    e["E7"] = [{"pdb_id": "4hhb", "style": "cartoon", "resolution": r}
               for r in ("800x800", "1280x720", "1080x1080", "1920x1080")]
    return e


def run_id(exp: str, cfg: dict) -> str:
    parts = [exp] + [f"{k}={cfg[k]}" for k in sorted(cfg)]
    return "|".join(str(p) for p in parts)


def render_one(exp: str, cfg: dict) -> dict:
    cfg = dict(cfg)
    tag = cfg.pop("tag", "")
    samples_override = cfg.pop("samples", None)
    threads = cfg.pop("threads", None) or SETTINGS.threads()
    request = RenderRequest(**cfg)
    samples = samples_override or request.samples
    name = "_".join(filter(None, [exp, request.pdb_id, request.style, request.color,
                                  request.quality if not samples_override else f"s{samples}",
                                  request.resolution, "asm" if request.assembly else "",
                                  f"t{threads}", tag])) + ".png"
    image = OUT / name
    row = {
        "experiment": exp, "pdb_id": request.pdb_id.upper(), "style": request.style,
        "color": request.color, "material": request.material, "quality": request.quality
        if not samples_override else "reference", "samples": samples,
        "resolution": request.resolution, "assembly": int(request.assembly),
        "threads": threads, "image": str(image.relative_to(ROOT)),
    }
    structure = fetch_structure(request.pdb_id, SETTINGS)
    SETTINGS.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SETTINGS.work_dir) as tmp:
        tmp_dir = Path(tmp)
        spec = {
            **request.model_dump(), "size": list(request.size), "samples": samples,
            "structure_path": str(structure), "output_path": str(image),
            "max_atoms": SETTINGS.max_atoms(request.style), "threads": threads,
        }
        spec_path = tmp_dir / "spec.json"
        spec_path.write_text(json.dumps(spec))
        log_path = tmp_dir / "blender.log"
        t0 = time.monotonic()
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                [sys.executable, "-m", "app.blender_render", str(spec_path)],
                cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                env=blender_environment(),
            )
            try:
                _, status, usage = _wait(proc, SETTINGS.render_timeout)
            except TimeoutError:
                proc.kill()
                proc.wait()
                return {**row, "status": "timeout", "wall_s": SETTINGS.render_timeout}
        wall = time.monotonic() - t0
        result_path = tmp_dir / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        row.update({
            "wall_s": round(wall, 1),
            "peak_rss_mb": round(usage.ru_maxrss / 1024),
        })
        if result.get("ok"):
            row.update({
                "status": "ok", "atoms_rendered": result.get("atoms"),
                "setup_s": result.get("setup_s"), "render_s": result.get("render_s"),
                "png_kb": round(image.stat().st_size / 1024),
            })
        elif result:
            row.update({"status": "refused", "error": result.get("error", "")[:200]})
        else:
            tail = log_path.read_text(errors="replace").splitlines()[-5:]
            row.update({"status": f"crash({os.waitstatus_to_exitcode(status)})",
                        "error": " / ".join(tail)[:300]})
    return row


def _wait(proc: subprocess.Popen, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            return pid, status, usage
        if time.monotonic() > deadline:
            raise TimeoutError
        time.sleep(0.2)


def write_run_info() -> None:
    """Record what was benchmarked: commit, versions and hardware."""
    from app import about
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
    info = {"date": time.strftime("%Y-%m-%d"), "commit": commit, "versions": about.versions(),
            "cpu": cpu, "threads": SETTINGS.threads(), "python": platform.python_version(),
            "memory_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)}
    (HERE / "run_info.json").write_text(json.dumps(info, indent=2))


def main(selected: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_run_info()
    SETTINGS.ensure_dirs()
    done = set()
    if CSV_PATH.exists():
        with open(CSV_PATH) as fh:
            done = {r["run_id"] for r in csv.DictReader(fh)}
    new_file = not CSV_PATH.exists()
    all_exps = experiments()
    with open(CSV_PATH, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for exp in selected or list(all_exps):
            for cfg in all_exps[exp]:
                rid = run_id(exp, cfg)
                if rid in done:
                    continue
                row = render_one(exp, cfg)
                row["run_id"] = rid
                writer.writerow(row)
                fh.flush()
                print(f"{rid}: {row.get('status')} wall={row.get('wall_s')}s "
                      f"render={row.get('render_s')}s rss={row.get('peak_rss_mb')}MB", flush=True)


if __name__ == "__main__":
    print(f"Python {platform.python_version()} on {platform.platform()}; "
          f"{SETTINGS.threads()} CPU threads", flush=True)
    main(sys.argv[1:])
