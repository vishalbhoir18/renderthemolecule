"""The double-click scripts for running the site on a Windows PC (README, "Test changes on your own PC")."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def script(name):
    data = (ROOT / name).read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), f"{name} needs Windows line endings"
    return data.decode("ascii")


def test_setup_installs_the_tested_packages_with_python_3_13():
    text = script("setup-windows.bat")
    assert "py -3.13" in text and "sys.version_info[:2] != (3, 13)" in text
    assert "-m pip install -r requirements-dev.txt" in text
    assert (ROOT / "requirements-dev.txt").exists()
    assert "import bpy, molecularnodes" in text  # fails early if Blender cannot load


def test_start_runs_the_app_and_reloads_only_on_app_changes():
    text = script("start-windows.bat")
    assert "-m uvicorn --factory app.main:create_app --port 7860" in text
    # Watching only app/ keeps the reloader away from the thousands of files in .venv.
    assert "--reload --reload-dir app" in text
    assert "http://localhost:7860" in text
