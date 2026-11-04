"""What a user can ask for, and how each choice is validated.

This module is imported by the web server *and* by the Blender render process,
so it must stay free of ``bpy`` / ``molecularnodes`` imports.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, get_args
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bump when the look of renders changes, so cached images are not reused.
RENDER_VERSION = "2"  # 2: credit line and PNG metadata

# Classic IDs (4HHB) and the extended wwPDB format (pdb_00004hhb).
PDB_ID_RE = re.compile(r"^(?:[1-9][a-z0-9]{3}|pdb_[0-9a-z]{8})$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_MAX = 100
EMAIL_MAX = 254
# Spreadsheets treat text starting with these as a formula.
FORMULA_START = ("=", "+", "-", "@")

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
    credit: bool = True  # small credit line in the corner of the image

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
        options = self.model_dump(include=set(RenderRequest.model_fields))
        payload = json.dumps({"v": RENDER_VERSION, **options}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def download_name(self) -> str:
        return f"{self.pdb_id}_{self.style}_{self.color}.png"

    def share_query(self) -> str:
        """Query string that reopens the page with these options (see app.js)."""
        params = {"id": self.pdb_id.upper()}
        for name in ("style", "color", "material", "viewpoint", "resolution", "quality", "background"):
            params[name] = getattr(self, name)
        for name in ("ligands", "assembly", "credit"):
            params[name] = "1" if getattr(self, name) else "0"
        return urlencode(params)


class Submission(RenderRequest):
    """What the web form posts: the render options plus who is asking.

    Name and email are recorded (see app/sheet.py) but are not part of the
    image cache key, so everyone shares cached renders.
    """

    name: str = Field(default="", validate_default=True)
    email: str = Field(default="", validate_default=True)

    @field_validator("name", mode="before")
    @classmethod
    def _check_name(cls, value: object) -> str:
        name = " ".join(value.split()) if isinstance(value, str) else ""
        if not name:
            raise ValueError("Please enter your name.")
        if len(name) > NAME_MAX:
            raise ValueError(f"Your name is too long (at most {NAME_MAX} characters).")
        if name.startswith(FORMULA_START):
            raise ValueError("Your name cannot start with =, +, - or @.")
        if not name.isprintable():
            raise ValueError("Your name contains characters that are not allowed.")
        return name

    @field_validator("email", mode="before")
    @classmethod
    def _check_email(cls, value: object) -> str:
        email = value.strip() if isinstance(value, str) else ""
        if not email:
            raise ValueError("Please enter your email address.")
        if (
            len(email) > EMAIL_MAX
            or not EMAIL_RE.fullmatch(email)
            or email.startswith(FORMULA_START)
            or not email.isprintable()
        ):
            raise ValueError("Please enter a valid email address, like name@university.edu.")
        return email.lower()

    def render_request(self) -> RenderRequest:
        return RenderRequest(**self.model_dump(exclude={"name", "email"}))


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
