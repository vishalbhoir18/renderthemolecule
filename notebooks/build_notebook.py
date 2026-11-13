"""Generate notebooks/render_the_molecule.ipynb.

The form's choices come from app/options.py and the system libraries from the
Dockerfile, so the notebook always matches the web app. After changing either,
run from the repository root:

    python notebooks/build_notebook.py

tests/test_notebook.py fails if the committed notebook is out of date.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import about  # noqa: E402
from app.options import LABELS, RenderRequest  # noqa: E402

NOTEBOOK = ROOT / "notebooks" / "render_the_molecule.ipynb"


def apt_packages() -> list[str]:
    text = (ROOT / "Dockerfile").read_text()
    block = re.search(r"apt-get install -y --no-install-recommends(.*?)&&", text, re.S).group(1)
    return block.replace("\\", " ").split()


def markdown(cell_id: str, text: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {"id": cell_id},
            "source": text.strip("\n").splitlines(keepends=True)}


def code(cell_id: str, text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "id": cell_id,
            "metadata": {"cellView": "form", "id": cell_id}, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def form_cell() -> str:
    defaults = RenderRequest.model_fields
    lines = [
        '#@title 1. Your details and the molecule { display-mode: "form" }',
        'name = ""  #@param {type:"string"}',
        'email = ""  #@param {type:"string"}',
        'institution = ""  #@param {type:"string"}',
        'country = ""  #@param {type:"string"}',
        f"#@markdown All four are required. {about.PRIVACY_SUMMARY}",
        f"#@markdown [Privacy notice]({about.PRIVACY_URL})",
        "#@markdown ---",
        'pdb_id = "4HHB"  #@param {type:"string"}',
    ]
    for field in ("style", "color", "material", "viewpoint", "resolution", "quality", "background"):
        choices = json.dumps(list(LABELS[field]))
        lines.append(f'{field} = "{defaults[field].default}"  #@param {choices}')
    for field in ("ligands", "assembly", "credit"):
        lines.append(f'{field} = {defaults[field].default}  #@param {{type:"boolean"}}')
    lines += [
        '#@markdown *Colour* "default" = by chain. *Material* "default" = glossy, lit by studio lights;',
        '#@markdown "ambient_occlusion" = soft and evenly lit. *Ligands*: show ligands and ions as ball-and-stick',
        "#@markdown (cartoon and ribbon). *Assembly*: the whole biological complex. *Credit*: small",
        "#@markdown credit line on the image (untick for a clean figure and cite in the text).",
        "",
        "form = dict(name=name, email=email, institution=institution, country=country, pdb_id=pdb_id,",
        "            style=style, color=color, material=material, viewpoint=viewpoint, resolution=resolution,",
        "            quality=quality, background=background, ligands=ligands, assembly=assembly, credit=credit)",
        "import re",
        "if (not name.strip() or not re.fullmatch(r\"[^@\\s]+@[^@\\s]+\\.[^@\\s]+\", email.strip())",
        "        or not institution.strip() or not country.strip() or not pdb_id.strip()):",
        '    raise SystemExit("Please fill in your name, a valid email, your institution, your country "',
        '                     "and a PDB ID in the form above, then run again.")',
        'print("Form OK:", pdb_id.strip().upper())',
    ]
    return "\n".join(lines)


def install_cell() -> str:
    packages = " ".join(apt_packages())
    return f'''
#@title 2. Install Blender and Molecular Nodes (first run only, about 1–2 minutes) {{ display-mode: "form" }}
import os, subprocess, sys
REPO_URL = "{about.REPO_URL}"
REPO_DIR = "/content/renderthemolecule"
VENV = "/content/rtm-venv"
PYTHON = f"{{VENV}}/bin/python"
INSTALLED = f"{{VENV}}/.installed"

def sh(command):
    subprocess.run(command, shell=True, check=True)

if not os.path.exists(INSTALLED):
    print("Installing Blender and Molecular Nodes (about 1–2 minutes)…")
    sh("apt-get -qq update > /dev/null && apt-get -qq install -y --no-install-recommends "
       "{packages} > /dev/null")
    sh("pip -q install uv")
    sh(f"uv venv -q --python 3.13 {{VENV}}")
# Always use the latest version of the code (fixes reach open sessions too).
if os.path.exists(REPO_DIR):
    sh(f"git -C {{REPO_DIR}} fetch -q --depth 1 origin main && git -C {{REPO_DIR}} reset -q --hard FETCH_HEAD")
else:
    sh(f"git clone -q --depth 1 {{REPO_URL}} {{REPO_DIR}}")
sh(f"uv pip install -q --python {{PYTHON}} -r {{REPO_DIR}}/requirements.txt")  # quick when up to date
open(INSTALLED, "w").close()
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
import importlib
from app import colab
colab = importlib.reload(colab)
print("Ready.")
'''


RENDER_CELL = '''
#@title 3. Render { display-mode: "form" }
from IPython.display import Image, Markdown, display
OUT_DIR = "/content/render-output"
result = colab.render(form, python=PYTHON, repo_dir=REPO_DIR, out_dir=OUT_DIR)
print(colab.record(result, f"{REPO_DIR}/notebooks/colab_recording.json"))
if result["ok"]:
    display(Image(filename=result["image"]))
    display(Markdown(colab.citation_markdown(result)))
else:
    print("Error:", result["error"])
'''

DOWNLOAD_CELL = '''
#@title 4. Download the image { display-mode: "form" }
from google.colab import files
if result.get("ok"):
    files.download(result["image"])
else:
    print("There is no image to download; see the error in step 3.")
'''


def build() -> dict:
    doi = about.APP_DOI
    intro = f"""
# Render the Molecule, in Google Colab

**by [{about.AUTHOR}]({about.AUTHOR_URL})** · [![DOI](https://zenodo.org/badge/DOI/{doi}.svg)](https://doi.org/{doi})

Publication-quality images of any Protein Data Bank entry, rendered with Blender and
Molecular Nodes on Google's free computers. Prefer a website? Use the
**[web app]({about.SITE_URL})**.

**How to use**

1. Fill in the form below: your name, email, institution and country, the PDB ID and the options.
2. Click **Runtime → Run all** (or press Ctrl+F9).
3. The first run installs Blender and Molecular Nodes (about 1–2 minutes). Each render then
   takes about 30–120 seconds.
4. The image appears under step 3 with how to cite it. Run step 4 to download it.

To render another molecule, change the form and run steps 1 and 3 again; the installation is
kept until the Colab session ends.

*Privacy: your name, email, institution, country and what you render are recorded privately.
{about.PRIVACY_SUMMARY} [Privacy notice]({about.PRIVACY_URL})*
"""
    outro = f"""
---
Render the Molecule App developed by [{about.AUTHOR}]({about.AUTHOR_URL})
([https://doi.org/{doi}](https://doi.org/{doi})). Images are rendered with
[Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) by Brady Johnston and
contributors, and [Blender](https://www.blender.org). Structures come from the
[RCSB Protein Data Bank](https://www.rcsb.org). Free software under the GNU GPL v3:
[source code]({about.REPO_URL}).
"""
    cells = [
        markdown("intro", intro),
        code("form", form_cell()),
        code("install", install_cell()),
        code("render", RENDER_CELL),
        code("download", DOWNLOAD_CELL),
        markdown("credits", outro),
    ]
    return {
        "cells": cells,
        "metadata": {
            "colab": {"name": "render_the_molecule.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def render_json(notebook: dict) -> str:
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    NOTEBOOK.write_text(render_json(build()))
    print(f"wrote {NOTEBOOK.relative_to(ROOT)}")
