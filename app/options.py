"""What a user can ask for, and how each choice is validated.

This module is imported by the web server *and* by the Blender render process,
so it must stay free of ``bpy`` / ``molecularnodes`` imports.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Literal, get_args
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Bump when the look of renders changes, so cached images are not reused.
RENDER_VERSION = "3"  # 2: credit line and PNG metadata; 3: DOI in metadata

# Classic IDs (4HHB) and the extended wwPDB format (pdb_00004hhb).
PDB_ID_RE = re.compile(r"^(?:[1-9][a-z0-9]{3}|pdb_[0-9a-z]{8})$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_MAX = 100
EMAIL_MAX = 254
INSTITUTION_MAX = 200
COUNTRY_MAX = 80
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


# A camera set in the browser's 3D preview (Mol*), rendered as-is by Blender.
CAMERA_COORD_MAX = 100_000.0  # ångström; far beyond any PDB entry
CAMERA_FOV_RANGE = (10.0, 130.0)  # degrees, the range Mol* offers


def _number_text(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class Camera(BaseModel):
    """A perspective camera, as set in the 3D preview.

    Coordinates are in ångström, in the frame of the structure file (Mol* and
    Molecular Nodes both keep it). ``fov`` is the vertical field of view in
    degrees, so the framing holds for any image width. Values are rounded so
    that the same view always gives the same cache key and share link.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float]
    fov: float = 45.0

    @field_validator("position", "target")
    @classmethod
    def _check_point(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(x) and abs(x) <= CAMERA_COORD_MAX for x in value):
            raise ValueError("camera coordinates must be numbers within ±100000 Å")
        return tuple(round(x, 2) + 0.0 for x in value)

    @field_validator("up")
    @classmethod
    def _check_up(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(x) for x in value) or math.hypot(*value) < 1e-3:
            raise ValueError("the camera's up direction must be a non-zero vector")
        return tuple(round(x, 4) + 0.0 for x in value)

    @field_validator("fov")
    @classmethod
    def _check_fov(cls, value: float) -> float:
        low, high = CAMERA_FOV_RANGE
        if not (math.isfinite(value) and low <= value <= high):
            raise ValueError(f"the field of view must be between {low:g} and {high:g} degrees")
        return round(value, 2)

    @model_validator(mode="after")
    def _check_geometry(self) -> Camera:
        forward = [t - p for t, p in zip(self.target, self.position)]
        if math.hypot(*forward) < 0.1:
            raise ValueError("the camera must be away from the point it looks at")
        side = _cross(forward, self.up)
        if math.hypot(*side) < 1e-3 * math.hypot(*forward) * math.hypot(*self.up):
            raise ValueError("the camera's up direction cannot point along its view")
        return self

    def to_param(self) -> str:
        """Compact form for links: px,py,pz,tx,ty,tz,ux,uy,uz,fov (see app.js)."""
        numbers = [_number_text(x, 2) for x in (*self.position, *self.target)]
        numbers += [_number_text(x, 4) for x in self.up]
        numbers.append(_number_text(self.fov, 2))
        return ",".join(numbers)

    @classmethod
    def from_param(cls, text: str) -> Camera:
        return cls(**_parse_camera_param(text))


def _parse_camera_param(text: str) -> dict:
    message = "a camera is written as 10 numbers separated by commas"
    parts = text.split(",")
    if len(parts) != 10:
        raise ValueError(message)
    try:
        v = [float(part) for part in parts]
    except ValueError:
        raise ValueError(message) from None
    return {"position": v[0:3], "target": v[3:6], "up": v[6:9], "fov": v[9]}


def _cross(a, b) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


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
    # The exact view from the 3D preview; replaces ``viewpoint`` when set.
    camera: Camera | None = None

    @model_validator(mode="before")
    @classmethod
    def _camera_replaces_viewpoint(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("camera") not in (None, ""):
            data = {**data, "viewpoint": "default"}
        return data

    @field_validator("camera", mode="before")
    @classmethod
    def _parse_camera(cls, value: object) -> object:
        """Also accept the compact text form used in links and by the CLI."""
        if value == "":
            return None
        return _parse_camera_param(value) if isinstance(value, str) else value

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
        if options["camera"] is None:
            del options["camera"]  # keeps the keys of earlier renders
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
        if self.camera is not None:
            params["cam"] = self.camera.to_param()
        return urlencode(params)


def _clean_text(value: object, label: str, max_len: int) -> str:
    """Shared checks for the free-text visitor fields (name, institution, country)."""
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not text:
        raise ValueError(f"Please enter your {label}.")
    if len(text) > max_len:
        raise ValueError(f"Your {label} is too long (at most {max_len} characters).")
    if text.startswith(FORMULA_START):
        raise ValueError(f"Your {label} cannot start with =, +, - or @.")
    if not text.isprintable():
        raise ValueError(f"Your {label} contains characters that are not allowed.")
    return text


VISITOR_FIELDS = ("name", "email", "institution", "country")


class Submission(RenderRequest):
    """What the web form posts: the render options plus who is asking.

    The visitor's details are recorded (see app/sheet.py) but are not part of
    the image cache key, so everyone shares cached renders.
    """

    name: str = Field(default="", validate_default=True)
    email: str = Field(default="", validate_default=True)
    institution: str = Field(default="", validate_default=True)
    country: str = Field(default="", validate_default=True)

    @field_validator("name", mode="before")
    @classmethod
    def _check_name(cls, value: object) -> str:
        return _clean_text(value, "name", NAME_MAX)

    @field_validator("institution", mode="before")
    @classmethod
    def _check_institution(cls, value: object) -> str:
        return _clean_text(value, "institution", INSTITUTION_MAX)

    @field_validator("country", mode="before")
    @classmethod
    def _check_country(cls, value: object) -> str:
        return _clean_text(value, "country", COUNTRY_MAX)

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
        return RenderRequest(**self.model_dump(exclude=set(VISITOR_FIELDS)))


def option_lists() -> dict:
    """Choices and defaults for the web form."""
    defaults = {
        name: field.default
        for name, field in RenderRequest.model_fields.items()
        if name not in ("pdb_id", "camera")
    }
    return {
        "choices": {
            field: [{"value": value, "label": label} for value, label in labels.items()]
            for field, labels in LABELS.items()
        },
        "defaults": defaults,
    }
