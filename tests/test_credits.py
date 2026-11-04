from PIL import Image, ImageDraw

from app import about
from app.blender_render import finish_image

VERSIONS = {"app": "0.1.0", "molecularnodes": "520.2.0", "blender": "5.2.2"}


def test_citation_texts():
    legend = about.legend_sentence("4hhb", VERSIONS)
    assert legend.startswith("The structure of PDB entry 4HHB was rendered with Render the Molecule")
    for part in ("v0.1.0; Bhoir, 2026", "Molecular Nodes (v520.2.0", "Blender (v5.2.2)", "Berman et al., 2000"):
        assert part in legend

    refs = about.references("4hhb", "https://me-rtm.hf.space", VERSIONS)
    assert refs[0].startswith("Bhoir, V. (2026). Render the Molecule (Version 0.1.0) [Web application]. https://me-rtm.hf.space")
    assert refs[1].endswith("Zenodo. https://doi.org/10.5281/zenodo.22827864")
    assert "Version 520.2.0" in refs[1]
    assert "Version 5.2.2" in refs[2]
    assert "10.1093/nar/28.1.235" in refs[3]
    assert refs[4].endswith("https://www.rcsb.org/structure/4HHB")
    assert about.references("4hhb", "", VERSIONS)[0].endswith(about.REPO_URL)

    assert about.credit_line("1ema") == "PDB 1EMA · Molecular Nodes · Render the Molecule by Vishal Bhoir"


def test_app_doi_is_used_once_set(monkeypatch):
    monkeypatch.setattr(about, "APP_DOI", "10.5281/zenodo.1234567")
    ref = about.references("4hhb", "https://me-rtm.hf.space", VERSIONS)[0]
    assert ref.endswith("[Web application]. Zenodo. https://doi.org/10.5281/zenodo.1234567 "
                        "(web application: https://me-rtm.hf.space)")
    assert about.rcsb_url("pdb_00004hhb") == "https://www.rcsb.org/structure/4HHB"


def raw_render(tmp_path, size=(1280, 720)):
    """A stand-in for Blender's output: a coloured blob on a transparent film."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    w, h = size
    ImageDraw.Draw(img).ellipse((w * 0.3, h * 0.2, w * 0.7, h * 0.8), fill=(40, 120, 200, 255))
    path = tmp_path / "raw.png"
    img.save(path)
    return path


def corner(img):
    w, h = img.size
    return img.crop((w // 2, int(h * 0.9), w, h)).convert("RGB")


def test_credit_line_and_metadata(tmp_path):
    raw = raw_render(tmp_path)
    spec = {"pdb_id": "4hhb", "background": "white", "credit": True}
    finish_image(raw, tmp_path / "with.png", spec, VERSIONS)
    finish_image(raw, tmp_path / "without.png", {**spec, "credit": False}, VERSIONS)

    with Image.open(tmp_path / "with.png") as with_credit, Image.open(tmp_path / "without.png") as plain:
        assert with_credit.mode == "RGB" and with_credit.size == (1280, 720)
        # Grey text in the bottom-right corner only when the credit line is on.
        assert corner(with_credit).getextrema() != ((255, 255), (255, 255), (255, 255))
        assert corner(plain).getextrema() == ((255, 255), (255, 255), (255, 255))
        for meta in (with_credit.text, plain.text):  # metadata is always there
            assert meta["Title"] == "PDB 4HHB, rendered with Render the Molecule"
            assert "Vishal Bhoir (ORCID https://orcid.org/0009-0004-8803-1967" in meta["Software"]
            assert "Molecular Nodes 520.2.0" in meta["Software"]
            assert meta["Source"].endswith("https://www.rcsb.org/structure/4HHB")
            assert meta["Description"] == about.legend_sentence("4hhb", VERSIONS)
            assert "10.1093/nar/28.1.235" in meta["Comment"]


def test_transparent_and_small_images(tmp_path):
    raw = raw_render(tmp_path, size=(320, 180))  # credit text must shrink to fit
    spec = {"pdb_id": "pdb_00001abc", "background": "transparent", "credit": True}
    finish_image(raw, tmp_path / "out.png", spec, VERSIONS)
    with Image.open(tmp_path / "out.png") as img:
        assert img.mode == "RGBA"
        assert img.getpixel((5, 5))[3] == 0  # background stays see-through
        assert corner(img).getextrema()[0][0] < 255  # credit drawn
