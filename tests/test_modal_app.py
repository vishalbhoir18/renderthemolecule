"""Checks on the Modal deployment file that need no Modal account."""

import importlib
import re
from pathlib import Path

import pytest

modal = pytest.importorskip("modal")
import modal_app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def dockerfile_apt_packages() -> list[str]:
    text = (ROOT / "Dockerfile").read_text()
    block = re.search(r"apt-get install -y --no-install-recommends(.*?)&&", text, re.S).group(1)
    return block.replace("\\", " ").split()


def test_same_system_libraries_and_base_as_the_tested_dockerfile():
    assert modal_app.APT_PACKAGES == dockerfile_apt_packages()
    assert f"FROM {modal_app.BASE_IMAGE}" in (ROOT / "Dockerfile").read_text()


def test_app_and_web_endpoint_are_defined():
    assert modal_app.app.name == "render-the-molecule"
    assert "web" in modal_app.app.registered_functions
    assert modal_app.MEMORY_MB >= 4096 and modal_app.CPU_CORES >= 1


def test_entry_point_builds_the_web_app(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(modal_app.web.local()) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Vishal Bhoir" in page.text


def web_dependencies(monkeypatch, local: bool) -> list[str]:
    """The objects Modal records for the web function, as seen locally or in the container."""
    from modal._utils.async_utils import synchronizer

    monkeypatch.setattr(modal, "is_local", lambda: local)
    module = importlib.reload(modal_app)
    return [type(dep).__name__ for dep in synchronizer._translate_in(module.web)._deps_()]


@pytest.mark.parametrize("sheet_settings", [True, False])
def test_same_dependencies_when_deployed_and_in_the_container(monkeypatch, sheet_settings):
    # Modal refuses to start a container whose function has different
    # dependencies from the deployed one ("Function has 1 dependencies but
    # container got 2 object ids"). This happened when the Sheet settings
    # made a Secret only on the deploying computer.
    for key in modal_app.DEPLOY_SETTINGS:
        monkeypatch.delenv(key, raising=False)
    if sheet_settings:
        monkeypatch.setenv("SHEET_WEBHOOK_URL", "https://script.google.com/macros/s/x/exec")
        monkeypatch.setenv("SHEET_TOKEN", "s3cret")
    try:
        deployed = web_dependencies(monkeypatch, local=True)
        in_container = web_dependencies(monkeypatch, local=False)
    finally:
        monkeypatch.undo()
        importlib.reload(modal_app)
    assert deployed == in_container
    assert "_Secret" in deployed
