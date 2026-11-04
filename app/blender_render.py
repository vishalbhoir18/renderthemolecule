"""Render one image with Blender + Molecular Nodes.

The web server runs this in a fresh process for every job, because Blender
keeps global state, holds on to memory and can crash outright:

    python -m app.blender_render /path/to/spec.json

It writes the PNG to ``spec["output_path"]`` and a ``result.json`` next to the
spec file: ``{"ok": true, ...}`` or ``{"ok": false, "error": "<for the user>"}``.
Unexpected failures exit non-zero with a traceback on stderr.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app import about
from app.options import ATOMIC_STYLES, BACKBONE_STYLES, BACKGROUND_RGB

# Non-polymer, non-water atoms: ligands, cofactors, ions.
LIGAND_SELECTION = "not protein and not nucleic and not water"


class UserFacingError(Exception):
    pass


def _material(mn, name: str):
    return {
        "ambient_occlusion": mn.material.AmbientOcclusion,
        "default": mn.material.Default,
        "flat": mn.material.Flat,
        "squishy": mn.material.Squishy,
    }[name]()


def _color(name: str):
    from molecularnodes.nodes import geometry as mg

    return {
        "default": None,  # keep Molecular Nodes' own per-chain / element colours
        "rainbow": lambda: mg.ColorRainbow(),
        "secondary_structure": lambda: mg.ColorSecondaryStructure(),
        # Goodsell needs a base colour: soft per-chain colours, carbons darkened.
        "goodsell": lambda: mg.ColorGoodsell(color=mg.RandomColor(mg.ChainID(), 3)),
    }[name]


def render(spec: dict) -> dict:
    import molecularnodes as mn

    timings = {}
    t0 = time.monotonic()
    style = spec["style"]
    engine = mn.scene.Cycles(
        samples=spec["samples"], device="CPU", denoise=True, denoise_gpu=False
    )
    canvas = mn.Canvas(engine, resolution=tuple(spec["size"]), transparent=True)
    if spec.get("threads"):
        canvas.scene.render.threads_mode = "FIXED"
        canvas.scene.render.threads = int(spec["threads"])

    mol = mn.Molecule.load(spec["structure_path"])
    n_atoms = mol.universe.atoms.n_atoms

    copies = 1
    if spec["assembly"]:
        assemblies = mol.assemblies() or {}
        transforms = assemblies.get("1") or next(iter(assemblies.values()), None)
        if not transforms:
            raise UserFacingError(
                "This entry has no biological assembly information. "
                "Untick “Biological assembly” and try again."
            )
        copies = len(transforms)

    # Upper bound: each transform may apply to only some chains.
    estimated = n_atoms * copies
    if estimated > spec["max_atoms"]:
        where = " in its biological assembly" if copies > 1 else ""
        raise UserFacingError(
            f"This structure has about {estimated:,} atoms{where}; the limit for "
            f"this style on this server is {spec['max_atoms']:,}. Try Cartoon"
            + (", or untick “Biological assembly”." if copies > 1 else ".")
        )

    selection = "not water" if style in ATOMIC_STYLES else None
    style_options = {}
    if style == "spheres" and spec["assembly"]:
        # Molecular Nodes 520.2.0: point-cloud spheres lose their material when
        # instanced over an assembly (they render plain grey); mesh spheres work.
        style_options["sphere"] = "Mesh"
    mol.add_style(
        style,
        selection=selection,
        material=_material(mn, spec["material"]),
        color=_color(spec["color"]),
        assembly=spec["assembly"],
        **style_options,
    )
    if spec["ligands"] and style in BACKBONE_STYLES:
        if mol.universe.select_atoms(LIGAND_SELECTION).n_atoms:
            mol.add_style(
                "ball_and_stick",
                selection=LIGAND_SELECTION,
                material=_material(mn, spec["material"]),
                assembly=spec["assembly"],
            )

    canvas.look_at(mol, viewpoint=spec["viewpoint"])
    timings["setup_s"] = round(time.monotonic() - t0, 1)

    output = Path(spec["output_path"])
    raw = output.with_name(output.stem + ".raw.png")
    t1 = time.monotonic()
    canvas.snapshot(str(raw))
    timings["render_s"] = round(time.monotonic() - t1, 1)

    finish_image(raw, output, spec, about.versions())
    raw.unlink(missing_ok=True)
    return {"atoms": estimated, **timings}


def finish_image(raw: Path, output: Path, spec: dict, versions: dict[str, str]) -> None:
    """Fill the background, add the credit line, and embed credits in the PNG."""
    from PIL import Image

    # Cycles renders with a transparent film; filling the background afterwards
    # keeps the lighting identical whatever background colour is chosen.
    image = Image.open(raw).convert("RGBA")
    rgb = BACKGROUND_RGB[spec["background"]]
    if rgb is not None:
        filled = Image.new("RGBA", image.size, (*rgb, 255))
        filled.alpha_composite(image)
        image = filled
    if spec.get("credit", True):
        _draw_credit(image, about.credit_line(spec["pdb_id"]), rgb)
    if rgb is not None:
        image = image.convert("RGB")
    image.save(output, optimize=True, pnginfo=png_metadata(spec["pdb_id"], versions))


def _draw_credit(image, text: str, background: tuple[int, int, int] | None) -> None:
    """Small grey text in the bottom-right corner, scaled to the image width."""
    from PIL import ImageDraw, ImageFont

    width, height = image.size
    margin = max(8, round(width / 100))
    size = max(11, round(width / 90))
    draw = ImageDraw.Draw(image)
    while True:
        font = ImageFont.load_default(size=size)
        left, _, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= width - 2 * margin or size <= 8:
            break
        size -= 1
    if background is None:
        fill = (128, 128, 128, 255)  # readable on light and dark pages
    elif sum(background) > 382:
        fill = (110, 110, 110, 255)
    else:
        fill = (165, 165, 165, 255)
    draw.text((width - margin - right, height - margin - bottom), text, font=font, fill=fill)


def png_metadata(pdb_id: str, versions: dict[str, str]):
    """Credits stored inside the PNG file (visible in image viewers' file info)."""
    from PIL.PngImagePlugin import PngInfo

    code = about.display_id(pdb_id)
    info = PngInfo()
    info.add_text("Title", f"PDB {code}, rendered with {about.APP_NAME}")
    info.add_text(
        "Software",
        f"{about.APP_NAME} {versions['app']} by {about.AUTHOR} "
        f"(ORCID {about.AUTHOR_ORCID}; {about.REPO_URL}); "
        f"Molecular Nodes {versions['molecularnodes']}; Blender {versions['blender']}",
    )
    info.add_text("Source", f"RCSB Protein Data Bank entry {code}: {about.rcsb_url(pdb_id)}")
    info.add_text("Description", about.legend_sentence(pdb_id, versions))
    info.add_text("Comment", "How to cite: " + " | ".join(about.references(pdb_id, "", versions)))
    return info


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 64
    spec_path = Path(argv[1])
    spec = json.loads(spec_path.read_text())
    try:
        result = {"ok": True, **render(spec)}
    except UserFacingError as exc:
        result = {"ok": False, "error": str(exc)}
    spec_path.with_name("result.json").write_text(json.dumps(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
