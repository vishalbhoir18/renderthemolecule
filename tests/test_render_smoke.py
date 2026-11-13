"""Real Blender render. Catches dependency drift in molecularnodes / bpy.

Skipped when molecularnodes is not installed. Uses RTM_TEST_STRUCTURE (a local
.bcif file) if set, otherwise downloads 1CRN from RCSB.
"""

import os
import shutil

import pytest

from app.errors import UserError
from app.options import Camera, RenderRequest
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
        {"style": "cartoon", "color": "rainbow", "background": "white"},
        {"style": "surface", "color": "goodsell", "background": "white"},
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


def test_renders_with_google_colabs_matplotlib_setting(settings, structure, tmp_path, monkeypatch):
    # Colab sets this; Biotite imports matplotlib, which crashed on the missing backend.
    monkeypatch.setenv("MPLBACKEND", "module://matplotlib_inline.backend_inline")
    request = RenderRequest(pdb_id="1crn", resolution="800x800", quality="draft")
    out = tmp_path / "out.png"
    run_blender(request, structure, out, settings)
    assert out.exists()


def test_atom_limit_is_reported_to_user(settings, structure, tmp_path):
    tiny = settings.__class__(data_dir=settings.data_dir, max_atoms_backbone=10)
    request = RenderRequest(pdb_id="1crn", resolution="800x800", quality="draft")
    with pytest.raises(UserError, match="limit"):
        run_blender(request, structure, tmp_path / "out.png", tiny)


def test_render_this_view_puts_the_molecule_where_the_preview_did(settings, structure, tmp_path):
    """A camera from the 3D preview is reproduced: position, aim, up direction and vertical field of view."""
    import biotite.structure.io.pdbx as pdbx
    import numpy as np

    coords = pdbx.get_structure(pdbx.BinaryCIFFile.read(str(structure)), model=1).coord
    centre = coords.mean(axis=0)
    radius = float(np.linalg.norm(coords - centre, axis=1).max())
    back = np.array([0.3, -0.5, 0.81]) / np.linalg.norm([0.3, -0.5, 0.81])
    forward = -back
    right = np.cross(forward, [0, 0, 1])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    # Aim right of and above the molecule, so it should appear left of and below the centre.
    target = centre + 0.25 * radius * right + 0.15 * radius * up
    position = target + 3 * radius * back
    camera = Camera(position=position.tolist(), target=target.tolist(), up=[0, 0, 1], fov=40)
    request = RenderRequest(pdb_id="1crn", resolution="1280x720", quality="draft", background="transparent",
                            credit=False, camera=camera)
    out = tmp_path / "out.png"
    run_blender(request, structure, out, settings)

    with PIL.open(out) as img:
        alpha = np.asarray(img)[..., 3].astype(float)
    height, width = alpha.shape
    ys, xs = np.nonzero(alpha)
    weights = alpha[ys, xs]
    seen = np.array([(xs * weights).sum(), (ys * weights).sum()]) / weights.sum()

    # Where a perspective camera with this vertical field of view projects the centre.
    d = centre - np.array(camera.position)
    depth, tan = d @ forward, np.tan(np.radians(camera.fov) / 2)
    expected = np.array([
        (1 + (d @ right) / (depth * tan * width / height)) / 2 * width,
        (1 - (d @ up) / (depth * tan)) / 2 * height,
    ])
    assert expected[0] < 0.45 * width and expected[1] > 0.55 * height  # a real offset to detect
    assert abs(seen[0] - expected[0]) < 0.025 * width
    assert abs(seen[1] - expected[1]) < 0.025 * height
