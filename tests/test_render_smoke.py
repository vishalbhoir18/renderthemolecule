"""Real Blender render. Catches dependency drift in molecularnodes / bpy.

Skipped when molecularnodes is not installed. Uses RTM_TEST_STRUCTURE (a local
.bcif file) if set, otherwise downloads 1CRN from RCSB.
"""

import os
import shutil

import pytest

from app.errors import UserError
from app.options import RenderRequest
from app.renderer import run_blender
from app.storage import fetch_structure

pytest.importorskip("molecularnodes")
PIL = pytest.importorskip("PIL.Image")


@pytest.fixture
def structure(settings):
    local = os.environ.get("RTM_TEST_STRUCTURE")
    if local:
        dest = settings.structures_dir / "test.bcif"
        shutil.copy(local, dest)
        return dest
    try:
        return fetch_structure("1crn", settings)
    except UserError as exc:
        pytest.skip(f"no test structure available: {exc}")


def colourful_fraction(img) -> float:
    """Share of pixels that are clearly coloured (not white, black or grey)."""
    hsv = img.convert("RGB").convert("HSV")
    pixels = list(hsv.getdata())
    return sum(1 for _, s, v in pixels if s > 60 and v > 40) / len(pixels)


@pytest.mark.parametrize(
    "options",
    [
        {"style": "cartoon", "background": "white"},
        {"style": "spheres", "color": "goodsell", "material": "flat", "background": "transparent"},
        # Point-cloud spheres lost their material when instanced over an assembly.
        {"style": "spheres", "assembly": True, "background": "white"},
    ],
)
def test_real_render(settings, structure, tmp_path, options):
    request = RenderRequest(pdb_id="1crn", resolution="800x800", quality="draft", **options)
    out = tmp_path / "out.png"
    info = run_blender(request, structure, out, settings)
    assert info["atoms"] > 0
    with PIL.open(out) as img:
        assert img.size == (800, 800)
        assert img.mode == ("RGBA" if options["background"] == "transparent" else "RGB")
        # The molecule was drawn with its colours, not as a grey or empty image.
        assert colourful_fraction(img) > 0.01


def test_atom_limit_is_reported_to_user(settings, structure, tmp_path):
    tiny = settings.__class__(data_dir=settings.data_dir, max_atoms_backbone=10)
    request = RenderRequest(pdb_id="1crn", resolution="800x800", quality="draft")
    with pytest.raises(UserError, match="limit"):
        run_blender(request, structure, tmp_path / "out.png", tiny)
