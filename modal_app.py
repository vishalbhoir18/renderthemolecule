"""Deploy Render the Molecule on Modal (https://modal.com).

Everything runs in one container: the web page, the job queue and Blender.
Modal starts the container when someone visits and stops it after
SCALEDOWN_SECONDS without requests, so credits are used only while the site
is in use. Step-by-step instructions: README, section "Deploy on Modal".

    pip install "modal==1.6.3"
    modal setup                    # once: log this computer in to Modal
    modal deploy modal_app.py

Optional settings are read from your environment when you deploy and handed to
the app: SHEET_WEBHOOK_URL and SHEET_TOKEN (Google Sheet record of renders) and
PUBLIC_URL (site address used in the Sheet's "Open again" links).
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent

APP_NAME = "render-the-molecule"
# The site will be at https://<your-modal-username>--render-the-molecule.modal.run
URL_LABEL = "render-the-molecule"

# Resources. Modal counts physical CPU cores, each with 2 hardware threads.
CPU_CORES = 2.0
MEMORY_MB = 8192  # one render peaks at about 2-3 GB; room for large structures
SCALEDOWN_SECONDS = 300  # how long the container stays up after the last request

# Same base image and system libraries as the Dockerfile, which CI builds and
# tests (tests/test_modal_app.py keeps the lists identical).
BASE_IMAGE = "python:3.13-slim-bookworm"
APT_PACKAGES = [
    "libegl1", "libegl-mesa0", "libgl1", "libgl1-mesa-dri", "libgomp1",
    "libsm6", "libx11-6", "libxext6", "libxfixes3", "libxi6", "libxkbcommon0", "libxrender1", "libxxf86vm1",
]
DEPLOY_SETTINGS = ("SHEET_WEBHOOK_URL", "SHEET_TOKEN", "PUBLIC_URL")

image = (
    modal.Image.from_registry(BASE_IMAGE)
    .apt_install(*APT_PACKAGES)
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .env({
        "DATA_DIR": "/tmp/renderthemolecule",
        # Container CPU counts can show the whole host; pin Blender's threads.
        "RENDER_THREADS": str(int(CPU_CORES * 2)),
    })
    .add_local_dir(HERE / "app", remote_path="/root/app", ignore=["**/__pycache__", "**/*.pyc"])
)


def settings_from_deploy_environment() -> list[modal.Secret]:
    """Pass the optional settings that are set on the deploying computer."""
    if not modal.is_local():  # inside the running container: already applied
        return []
    values = {key: os.environ[key] for key in DEPLOY_SETTINGS if os.environ.get(key)}
    return [modal.Secret.from_dict(values)] if values else []


app = modal.App(APP_NAME)


@app.function(
    image=image,
    cpu=CPU_CORES,
    memory=MEMORY_MB,
    secrets=settings_from_deploy_environment(),
    # The job queue lives in this container's memory, so every visitor must
    # reach the same container: never start a second one.
    max_containers=1,
    scaledown_window=SCALEDOWN_SECONDS,
)
@modal.concurrent(max_inputs=100)  # many visitors' page loads and status checks at once
@modal.asgi_app(label=URL_LABEL)
def web():
    from app.main import create_app  # the "app" package, not the Modal app above

    return create_app()
