"""The Colab notebook and the GitHub Pages landing page."""

import json
import re
import runpy
from pathlib import Path

import pytest

from app import about
from app.options import LABELS

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = ROOT / "notebooks" / "render_the_molecule.ipynb"


@pytest.fixture(scope="module")
def builder():
    return runpy.run_path(str(ROOT / "notebooks" / "build_notebook.py"))


@pytest.fixture(scope="module")
def notebook():
    return json.loads(NOTEBOOK.read_text())


def cell(notebook, cell_id):
    return "".join(next(c for c in notebook["cells"] if c["id"] == cell_id)["source"])


def test_committed_notebook_is_up_to_date(builder):
    expected = builder["render_json"](builder["build"]())
    assert NOTEBOOK.read_text() == expected, "run: python notebooks/build_notebook.py"


def test_code_cells_compile(notebook):
    for c in notebook["cells"]:
        if c["cell_type"] == "code":
            compile("".join(c["source"]), c["id"], "exec")


def test_form_offers_exactly_the_web_app_choices(notebook):
    form = cell(notebook, "form")
    for field, labels in LABELS.items():
        line = re.search(rf"^{field} = .*#@param (\[.*\])$", form, re.M)
        assert line and json.loads(line.group(1)) == list(labels), field


def test_form_stops_early_when_details_are_missing(notebook):
    with pytest.raises(SystemExit, match="Please fill in your name"):
        exec(cell(notebook, "form"), {})
    filled = (cell(notebook, "form").replace('name = ""', 'name = "Ada"').replace('email = ""', 'email = "a@b.org"')
              .replace('institution = ""', 'institution = "IISc"').replace('country = ""', 'country = "India"'))
    namespace = {}
    exec(filled, namespace)
    assert namespace["form"]["name"] == "Ada" and namespace["form"]["pdb_id"] == "4HHB"
    assert set(namespace["form"]) == {"name", "email", "institution", "country", "pdb_id", *LABELS,
                                      "ligands", "assembly", "credit"}
    # Each visitor detail is required on its own.
    for field in ("name", "email", "institution", "country"):
        missing = filled.replace(f'{field} = "{namespace[field]}"', f'{field} = ""')
        with pytest.raises(SystemExit):
            exec(missing, {})


def test_install_cell_uses_the_dockerfile_libraries(notebook, builder):
    install = cell(notebook, "install")
    assert " ".join(builder["apt_packages"]()) in install
    assert "requirements.txt" in install and about.REPO_URL in install


def test_recording_settings_file_and_links(notebook):
    settings = json.loads((ROOT / "notebooks" / "colab_recording.json").read_text())
    assert {"url", "key"} <= set(settings)
    assert about.COLAB_URL.endswith("/blob/main/" + str(NOTEBOOK.relative_to(ROOT)))
    intro = cell(notebook, "intro")
    assert about.SITE_URL in intro and about.APP_DOI in intro and about.AUTHOR_URL in intro


def test_landing_page_links_and_images():
    page = (ROOT / "docs" / "index.html").read_text()
    for url in (about.SITE_URL, about.COLAB_URL, f"https://doi.org/{about.APP_DOI}", about.AUTHOR_URL):
        assert url in page, url
    images = re.findall(r'src="(images/[^"]+)"', page)
    assert images
    for image in images:
        assert (ROOT / "docs" / image).exists(), image
    assert (ROOT / "docs" / ".nojekyll").exists()


def test_privacy_notice_everywhere(notebook):
    web = (ROOT / "app" / "static" / "privacy.html").read_text()
    assert (ROOT / "docs" / "privacy.html").read_text() == web, "keep docs/privacy.html a copy of app/static/privacy.html"
    for sentence in about.PRIVACY_SUMMARY.split(". "):
        assert sentence.rstrip(".") in " ".join(web.split())
    assert about.PRIVACY_URL.endswith("/privacy.html")
    assert about.PRIVACY_URL in cell(notebook, "intro") and about.PRIVACY_URL in cell(notebook, "form")
    assert about.PRIVACY_SUMMARY in cell(notebook, "form")
    landing = (ROOT / "docs" / "index.html").read_text()
    assert 'href="privacy.html"' in landing
    assert "not be shared or used for marketing without your separate consent" in " ".join(landing.split())
    app_page = (ROOT / "app" / "static" / "index.html").read_text()
    assert app_page.count('href="/privacy"') == 2  # next to the fields and in the footer
