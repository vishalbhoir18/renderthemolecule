"""Who made this, which versions it uses, and how to cite an image.

Single source for the credit line on images, the PNG metadata, the page's
"How to cite" box and the README. Pure Python: imported by the web server and
by the Blender render process.
"""

from __future__ import annotations

from importlib import metadata

APP_NAME = "Render the Molecule"
APP_VERSION = "0.1.0"
AUTHOR = "Vishal Bhoir"
AUTHOR_APA = "Bhoir, V."
AUTHOR_ORCID = "https://orcid.org/0009-0004-8803-1967"
LICENSE = "GPL-3.0-or-later"
REPO_URL = "https://github.com/vishalbhoir18/renderthemolecule"
AUTHOR_URL = "https://linktr.ee/thebioway"
# Where the tool can be used.
SITE_URL = "https://vishalbhoir18--render-the-molecule.us-east.modal.run"  # web app (Modal)
PAGES_URL = "https://vishalbhoir18.github.io/renderthemolecule/"  # landing page (docs/)
PRIVACY_URL = PAGES_URL + "privacy.html"  # docs/privacy.html (same text as /privacy in the web app)
# The short notice shown wherever details are asked for (web form, notebook, landing page).
PRIVACY_SUMMARY = (
    "Your information will be used to understand academic adoption and improve the application. "
    "It will not be shared or used for marketing without your separate consent."
)
COLAB_URL = (
    "https://colab.research.google.com/github/vishalbhoir18/renderthemolecule/"
    "blob/main/notebooks/render_the_molecule.ipynb"
)
YEAR = "2026"
# DOI of this tool once archived on Zenodo (e.g. "10.5281/zenodo.1234567"); see README.
APP_DOI = "10.5281/zenodo.23960655"  # Zenodo record of release v0.1.0

# Molecular Nodes has no paper yet; its README asks to be cited via Zenodo.
MN_DOI = "10.5281/zenodo.22827864"
PDB_REFERENCE = (
    "Berman, H. M., Westbrook, J., Feng, Z., Gilliland, G., Bhat, T. N., Weissig, H., "
    "Shindyalov, I. N., & Bourne, P. E. (2000). The Protein Data Bank. "
    "Nucleic Acids Research, 28(1), 235–242. https://doi.org/10.1093/nar/28.1.235"
)


def package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def versions() -> dict[str, str]:
    return {
        "app": APP_VERSION,
        "molecularnodes": package_version("molecularnodes"),
        "blender": package_version("bpy"),
    }


def display_id(pdb_id: str) -> str:
    """4hhb -> 4HHB, pdb_00004hhb -> PDB_00004HHB."""
    return pdb_id.upper()


def rcsb_url(pdb_id: str) -> str:
    code = pdb_id.lower()
    if code.startswith("pdb_0000"):  # extended form of a classic 4-character ID
        code = code[-4:]
    return f"https://www.rcsb.org/structure/{code.upper()}"


def credit_line(pdb_id: str) -> str:
    """Short credit drawn on the image."""
    return f"PDB {display_id(pdb_id)} · Molecular Nodes · {APP_NAME} by {AUTHOR}"


def legend_sentence(pdb_id: str, v: dict[str, str] | None = None) -> str:
    """One sentence for a figure legend or methods section."""
    v = v or versions()
    return (
        f"The structure of PDB entry {display_id(pdb_id)} was rendered with {APP_NAME} "
        f"(v{v['app']}; {AUTHOR_APA.split(',')[0]}, {YEAR}) using Molecular Nodes "
        f"(v{v['molecularnodes']}; Johnston et al.) and Blender (v{v['blender']}); "
        f"structure data from the RCSB Protein Data Bank (Berman et al., 2000)."
    )


def references(pdb_id: str, site_url: str = "", v: dict[str, str] | None = None) -> list[str]:
    """APA 7 reference list entries for an image of ``pdb_id``."""
    v = v or versions()
    code = display_id(pdb_id)
    if APP_DOI:
        where = f"Zenodo. https://doi.org/{APP_DOI}"
        if site_url:
            where += f" (web application: {site_url})"
    else:
        where = f"{site_url} (source code: {REPO_URL})" if site_url else REPO_URL
    return [
        f"{AUTHOR_APA} ({YEAR}). {APP_NAME} (Version {v['app']}) [Web application]. {where}",
        f"Johnston, B., & Molecular Nodes contributors. ({YEAR}). Molecular Nodes "
        f"(Version {v['molecularnodes']}) [Computer software]. Zenodo. https://doi.org/{MN_DOI}",
        f"Blender Online Community. ({YEAR}). Blender (Version {v['blender']}) "
        f"[Computer software]. Blender Foundation. https://www.blender.org",
        PDB_REFERENCE,
        f"The primary publication of PDB entry {code}, listed on its RCSB page: "
        f"{rcsb_url(pdb_id)}",
    ]
