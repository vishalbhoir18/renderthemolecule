"""What a user can ask for, and how each choice is validated.

This module is imported by the web server *and* by the Blender render process,
so it must stay free of ``bpy`` / ``molecularnodes`` imports.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, field_validator

# Bump when the look of renders changes, so cached images are not reused.
RENDER_VERSION = "1"

# Classic IDs (4HHB) and the extended wwPDB format (pdb_00004hhb).
PDB_ID_RE = re.compile(r"^(?:[1-9][a-z0-9]{3}|pdb_[0-9a-z]{8})$")

Style = Literal["cartoon", "ribbon", "surface", "spheres", "ball_and_stick", "sticks"]
ColorScheme = Literal["default", "rainbow", "secondary_structure", "goodsell"]
Material = Literal["ambient_occlusion", "default", "flat", "squishy"]
Viewpoint = Literal["default", "front", "back", "top", "bottom", "left", "right"]
Resolution = Literal["1280x720", "1920x1080", "1080x1080", "800x800"]
Quality = Literal["draft", "standard", "high"]
Background = Literal["white", "transparent", "black"]

LABELS: dict[str, dict[str, str]] = {
    "style": {
        "cartoon": "Cartoon",
        "ribbon": "Ribbon",
        "surface": "Surface",
        "spheres": "Spheres",
        "ball_and_stick": "Ball and stick",
        "sticks": "Sticks",
    },
    "color": {
        "default": "By chain",
        "rainbow": "Rainbow",
        "secondary_structure": "Secondary structure",
        "goodsell": "Goodsell",
    },
    "material": {
        "ambient_occlusion": "Ambient occlusion (soft)",
        "default": "Glossy",
        "flat": "Flat",
        "squishy": "Squishy",
    },
    "viewpoint": {
        "default": "Default",
        "front": "Front",
        "back": "Back",
        "top": "Top",
        "bottom": "Bottom",
        "left": "Left",
        "right": "Right",
    },
    "resolution": {
        "1280x720": "1280 × 720",
        "1920x1080": "1920 × 1080",
        "1080x1080": "1080 × 1080",
        "800x800": "800 × 800",
    },
    "quality": {
        "draft": "Draft (fast)",
        "standard": "Standard",
        "high": "High (slow)",
    },
    "background": {
        "white": "White",
        "transparent": "Transparent",
        "black": "Black",
    },
}

# Cycles samples per quality level. The denoiser makes low counts look clean.
SAMPLES: dict[str, int] = {"draft": 16, "standard": 32, "high": 64}

BACKGROUND_RGB: dict[str, tuple[int, int, int] | None] = {
    "white": (255, 255, 255),
    "transparent": None,
    "black": (0, 0, 0),
}

# Styles that only draw the polymer backbone; ligands are overlaid on these.
BACKBONE_STYLES = {"cartoon", "ribbon"}
# Styles that draw every atom, so water is hidden from them.
ATOMIC_STYLES = {"surface", "spheres", "ball_and_stick", "sticks"}

for _field, _literal in [
    ("style", Style),
    ("color", ColorScheme),
    ("material", Material),
    ("viewpoint", Viewpoint),
    ("resolution", Resolution),
    ("quality", Quality),
    ("background", Background),
]:
    assert set(LABELS[_field]) == set(get_args(_literal)), _field


class RenderRequest(BaseModel):
    """One render job as submitted by the web form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pdb_id: str
    style: Style = "cartoon"
    color: ColorScheme = "default"
    material: Material = "ambient_occlusion"
    viewpoint: Viewpoint = "default"
    resolution: Resolution = "1280x720"
    quality: Quality = "standard"
    background: Background = "white"
    assembly: bool = False
    ligands: bool = True

    @field_validator("pdb_id", mode="before")
    @classmethod
    def _normalise_pdb_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("PDB ID must be text, for example 4HHB")
        code = value.strip().lower()
        if not PDB_ID_RE.fullmatch(code):
            raise ValueError(
                f"'{value.strip()[:20]}' is not a valid PDB ID. "
                "Use a 4-character code such as 4HHB."
            )
        return code

    @property
    def size(self) -> tuple[int, int]:
        width, height = self.resolution.split("x")
        return int(width), int(height)

    @property
    def samples(self) -> int:
        return SAMPLES[self.quality]

    def cache_key(self) -> str:
        """Content hash: identical requests map to the same image file."""
        payload = json.dumps(
            {"v": RENDER_VERSION, **self.model_dump()}, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def download_name(self) -> str:
        return f"{self.pdb_id}_{self.style}_{self.color}.png"


def option_lists() -> dict:
    """Choices and defaults for the web form."""
    defaults = {
        name: field.default
        for name, field in RenderRequest.model_fields.items()
        if name != "pdb_id"
    }
    return {
        "choices": {
            field: [{"value": value, "label": label} for value, label in labels.items()]
            for field, labels in LABELS.items()
        },
        "defaults": defaults,
    }
