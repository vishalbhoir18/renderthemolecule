"""Checks on the Modal deployment file that need no Modal account."""

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


def test_optional_settings_come_from_the_deploy_environment(monkeypatch):
    for key in modal_app.DEPLOY_SETTINGS:
        monkeypatch.delenv(key, raising=False)
    assert modal_app.settings_from_deploy_environment() == []
    monkeypatch.setenv("SHEET_WEBHOOK_URL", "https://script.google.com/macros/s/x/exec")
    monkeypatch.setenv("SHEET_TOKEN", "s3cret")
    secrets = modal_app.settings_from_deploy_environment()
    assert len(secrets) == 1 and isinstance(secrets[0], modal.Secret)
