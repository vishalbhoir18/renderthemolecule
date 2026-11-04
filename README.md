---
title: Render the Molecule
emoji: 🧬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Publication-quality images from a PDB ID (Blender + Molecular Nodes)
---

# Render the Molecule

Type a Protein Data Bank ID (for example `4HHB`) and get a publication-quality
image back, rendered by [Blender](https://www.blender.org) with the
[Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) add-on.
No Blender installation is needed on the visitor's side; everything runs on the server.

Options: style (cartoon, ribbon, surface, spheres, ball-and-stick, sticks),
colour (by chain, rainbow, secondary structure, Goodsell), material, viewpoint,
image size, quality, white/black/transparent background, ligand highlighting
and biological assemblies.

## How it works

```
Browser ──▶ FastAPI (app/main.py)
              │ validate the PDB ID and options
              │ same picture rendered before? → return it immediately (cache)
              │ else put a job in the queue → job id
              ▼
            In-memory queue + one worker thread (app/jobs.py), one render at a time
              │ 1. download <id>.bcif from RCSB (app/storage.py)
              │ 2. run `python -m app.blender_render spec.json` in a new process
              │    (bpy + molecularnodes → Cycles on the CPU → PNG)
              ▼
            data/renders/<sha256 of options>.png  ◀── browser polls /api/jobs/<id>, then loads the image
```

* **Blender as a Python module.** `pip install "molecularnodes[bpy]"` brings Blender in as the
  `bpy` package. There is no Blender binary to install and no add-on to enable.
* **Cycles, not EEVEE.** Without a GPU, EEVEE runs through software OpenGL. On a 4-vCPU test
  machine it was slower than Cycles at 32 samples with the CPU denoiser (29 s vs 20 s).
* **One process per render.** Blender keeps global state and can crash; a fresh process per job
  keeps the web server alive and returns all memory after every render.
* **No Redis/Celery.** A free Hugging Face Space is a single container, so the queue lives in
  memory. One worker is right anyway: Cycles already uses every CPU core.
* **Content-addressed cache.** Each image is named by a hash of its options, so a repeated
  request (or a shared link) is served instantly.

Measured on a 4-vCPU machine at 1280 × 720: 15–23 s per image at *Standard* quality and about
9 s at *Draft*, plus 3–4 s of scene setup. The free Hugging Face tier has 2 vCPUs, so expect
those times to roughly double there.

## Deploy free on Hugging Face Spaces

1. Create a free account at <https://huggingface.co> and click **New Space**.
   Choose **Docker** → **Blank**, hardware **CPU basic (free)**, then create it.
2. Create an access token with **write** permission (Settings → Access Tokens).
3. Push this repository to the Space; use the token as the password when asked:

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
   ```

   ```bash
   git push space main
   ```

The Space builds the Docker image (a few minutes the first time) and then serves the app at
`https://<your-username>-<space-name>.hf.space`.

**Automatic deploys from GitHub (optional).** In the GitHub repository settings, add a
secret `HF_TOKEN` (the token above) and a variable `HF_SPACE` (`<your-username>/<space-name>`).
After that, every push to `main` that passes CI is deployed by `.github/workflows/ci.yml`.

Things to know about the free tier: the Space sleeps after 48 hours without visitors and the
next visitor wakes it (the first load then takes a minute or two); its disk is wiped on
restart, so the image cache starts empty again; the CPUs are shared.

## Run it elsewhere

The same image runs on any **x86-64** Docker host. Google Cloud Run and Cloudflare Containers
work too; the container reads `PORT` if it is set. ARM machines (for example Oracle's free
Ampere servers) do not work, because `bpy` has no Linux ARM build.

```bash
docker build -t renderthemolecule .
```

```bash
docker run --rm -p 7860:7860 renderthemolecule
```

Then open <http://localhost:7860>.

Without Docker (Linux x86-64, Python 3.13; install the system libraries listed in the
`Dockerfile` first):

```bash
python3.13 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
uvicorn --factory app.main:create_app --port 7860
```

## Configuration

All settings are environment variables (see `app/config.py`).

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | Where structures, renders and temp files go |
| `RENDER_TIMEOUT` | `600` | Seconds before a render is stopped |
| `RENDER_THREADS` | auto | Cycles threads; auto reads the container's CPU quota |
| `MAX_QUEUE` | `20` | Waiting jobs before new ones are refused |
| `MAX_ACTIVE_PER_CLIENT` | `3` | Waiting + running jobs per visitor |
| `MAX_DOWNLOAD_MB` | `200` | Largest structure file accepted |
| `MAX_ATOMS_BACKBONE` / `_ATOMIC` / `_BONDS` | 3M / 1M / 300k | Atom limits for cartoon+ribbon / surface+spheres / sticks+ball-and-stick |
| `RENDERS_CACHE_MB`, `STRUCTURES_CACHE_MB` | `2000` | Disk caches; oldest files are deleted first |
| `STRUCTURE_URL` | `https://models.rcsb.org/{code}.bcif` | Download source |

## API

* `POST /api/render` with JSON such as `{"pdb_id": "4HHB", "style": "surface"}` returns a job (HTTP 202).
* `GET /api/jobs/{id}` returns `status` (`queued` / `running` / `done` / `failed`), `jobs_ahead`, `image_url` and `error`.
* `GET /api/options` lists every choice and its default; interactive docs are at `/api/docs`.

## Development

```bash
pytest
```

The suite includes a real Blender render of PDB 1CRN, downloaded from RCSB. Set
`RTM_TEST_STRUCTURE=/path/to/file.bcif` to use a local file instead.

**Updating Molecular Nodes.** `requirements.txt` pins every package. This is deliberate:
`molecularnodes` only sets minimum versions for its dependencies, and newer `nodebpy` releases
(520.37 and later) stop `molecularnodes` 520.2.0 from importing at all. To upgrade, install the
new release with everything as of its release date, run the tests and freeze:

```bash
uv pip install --exclude-newer <release-date+1> "molecularnodes[bpy]==<version>" pillow requests fastapi uvicorn
```

Bump `RENDER_VERSION` in `app/options.py` when the look of renders changes so old cached
images are not reused.

## Credits and licences

Images are made with Blender (GPL) and Molecular Nodes by Brady Johnston (GPL-3.0); structures
come from the RCSB Protein Data Bank. If you publish an image, please cite Molecular Nodes and
the PDB entry. Because this app imports GPL-3.0 code, release your copy under a GPL-compatible
licence if you distribute it.
