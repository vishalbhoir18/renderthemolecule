"""Print the benchmark rows the manuscript's charts are drawn from, as JS literals.

    python paper/benchmark/chart_rows.py scaling   # E1: atoms, wall time, memory per style
    python paper/benchmark/chart_rows.py quality   # E3: samples, render time, SSIM

The output is pasted into the chart widgets' `sources`, so every plotted
value comes from results.csv / summary.json unchanged.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def scaling():
    rows = []
    with open(HERE / "results.csv") as fh:
        for r in csv.DictReader(fh):
            if r["experiment"] != "E1":
                continue
            rows.append({
                "id": r["pdb_id"], "style": r["style"], "status": r["status"],
                "atoms": int(r["atoms_rendered"]) if r["atoms_rendered"] else None,
                "wall": float(r["wall_s"]) if r["wall_s"] else None,
                "render": float(r["render_s"]) if r["render_s"] else None,
                "gb": round(float(r["peak_rss_mb"]) / 1024, 2) if r["peak_rss_mb"] else None,
            })
    return rows


def quality():
    summary = json.loads((HERE / "summary.json").read_text())
    return [{"id": q["pdb_id"], "style": q["style"], "samples": q["samples"],
             "render": q["render_s"], "ssim": q["ssim"]}
            for q in summary["image_quality"] if q["quality"] != "reference"]


def js(rows):
    def val(v):
        if v is None:
            return "null"
        if isinstance(v, str):
            return "'" + v + "'"
        return json.dumps(v)
    return "[" + ",".join("{" + ", ".join(f"{k}:{val(v)}" for k, v in r.items()) + "}" for r in rows) + "]"


if __name__ == "__main__":
    print(js({"scaling": scaling, "quality": quality}[sys.argv[1]]()))
