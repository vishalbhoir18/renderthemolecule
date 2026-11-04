import io
import threading
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.errors import UserError


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buf, "PNG")
    return buf.getvalue()


PNG_BYTES = _tiny_png()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", max_queue=3, max_active_per_client=2)
    s.ensure_dirs()
    return s


class FakeRenderer:
    """Stands in for Blender: writes a PNG, optionally waits or fails."""

    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()
        self.fail_with: Exception | None = None

    def __call__(self, request, output, set_stage):
        self.calls.append(request)
        set_stage("downloading")
        set_stage("rendering")
        self.gate.wait(10)
        if self.fail_with:
            raise self.fail_with
        output.write_bytes(PNG_BYTES)


@pytest.fixture
def fake_renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def user_error_cls():
    return UserError
