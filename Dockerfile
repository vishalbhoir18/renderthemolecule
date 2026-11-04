# Render the Molecule: FastAPI + Blender (as the bpy Python module) + Molecular Nodes.
# CPU only. Runs on Hugging Face Spaces (Docker), Google Cloud Run, Cloudflare
# Containers or any x86-64 Docker host. Not ARM: bpy has no Linux ARM wheel.
FROM python:3.13-slim-bookworm

# Shared libraries bpy loads at start-up. Mesa gives Blender a software
# OpenGL/EGL so it initialises without a GPU; images are rendered by Cycles on the CPU.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri libgomp1 \
      libsm6 libx11-6 libxext6 libxfixes3 libxi6 libxkbcommon0 libxrender1 libxxf86vm1 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/home/user/data
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --user -r requirements.txt

COPY --chown=user app ./app

# Fail the build early if Blender or Molecular Nodes cannot load.
RUN python -W ignore -c "import bpy, molecularnodes; print('Blender', bpy.app.version_string)"

EXPOSE 7860
# PORT is set by Cloud Run; Hugging Face uses app_port (7860) from README.md.
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT:-7860}"]
