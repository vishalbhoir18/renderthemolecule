"""Turn the editable manuscript's exports into the repository's manuscript files.

    python paper/build_manuscript_files.py <markdown-export.json> <docx-export.json>

The two arguments are the JSON results of the docs tool's markdown and docx
exports (data.bytes_b64 holds the file). Writes paper/manuscript.md (figure
placeholders replaced by links to paper/figures) and paper/manuscript.docx
(WebP pictures, which Word cannot show, replaced by the PNG files).
"""
import base64
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

FIGURES = {  # start of the export's placeholder text -> (markdown image, PNG for Word)
    "embedded content: Figure 1": ("Figure 1. Request flow", "figures/figure1_request_flow.png"),
    "image: Haemoglobin 4HHB": ("Figure 2. Haemoglobin in every representation and colour scheme", "figures/figure2_styles_4hhb.png"),
    "embedded content: Figure 3": ("Figure 3. Time and memory against structure size", "figures/figure3_scaling.png"),
    "image: Eight benchmark renders": ("Figure 4. Benchmark gallery", "figures/figure4_gallery.png"),
    "embedded content: Figure 5": ("Figure 5. Image fidelity against path-tracing time", "figures/figure5_quality.png"),
    "image: The same region of 4HHB": ("Supplementary Figure S1. Sample-budget crops", "figures/figureS1_sample_crops.png"),
    "image: Mol": ("Figure 6. Preview against render", "figures/figure6_preview_vs_render.png"),
}


def decode(path: str) -> tuple[bytes, list]:
    data = json.load(open(path))["data"]
    return base64.b64decode(data["bytes_b64"]), data.get("notes", [])


def build_markdown(path: str) -> None:
    md = decode(path)[0].decode()
    for key, (alt, png) in FIGURES.items():
        pattern = r"&#91;" + re.escape(key) + r"[^\]]*\\\]"
        md, n = re.subn(pattern, f"![{alt}]({png})", md)
        if n != 1:
            raise SystemExit(f"expected one placeholder for {key!r}, found {n}")
    if "&#91;" in md:
        raise SystemExit("an unknown placeholder is left in the markdown")
    md = re.sub(r"^# (.+)\n\n[^\n]*· @[^\n]*", lambda m: f"# {m.group(1)}\n\n"
                "*Working copy exported from the editable manuscript. Figures 1, 3 and 5 are drawn "
                "in the editable version; the files linked here are static renderings of the same "
                "data for journal submission.*", md, count=1)
    (HERE / "manuscript.md").write_text(md)


def build_docx(path: str) -> None:
    from docx import Document
    from docx.shared import Cm

    blob, notes = decode(path)
    out = HERE / "manuscript.docx"
    out.write_bytes(blob)
    doc = Document(out)
    for p in doc.paragraphs:
        text = p.text.strip()
        for key, (_, png) in FIGURES.items():
            if text.startswith("[" + key):
                for run in p.runs:
                    run.text = ""
                (p.runs[0] if p.runs else p.add_run()).add_picture(str(HERE / png), width=Cm(16))
    doc.save(out)
    left = [p.text for p in Document(out).paragraphs if p.text.strip().startswith("[image:")]
    if left:
        raise SystemExit(f"pictures left as text: {left}")
    print("docx notes from the export:", notes)


if __name__ == "__main__":
    build_markdown(sys.argv[1])
    build_docx(sys.argv[2])
