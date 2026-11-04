---
title: Render the Molecule
emoji: 🧬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: gpl-3.0
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
and biological assemblies. Visitors give their name and email, and every render
can be recorded in a private Google Sheet (see below). Each image credits its
sources and comes with a ready-made citation.

Developed by **Vishal Bhoir** ([ORCID 0009-0004-8803-1967](https://orcid.org/0009-0004-8803-1967)).
Free software under the GNU GPL v3 or later.

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

## Record who rendered what in a Google Sheet

Visitors must enter their **name and email** before rendering. Each finished request
(including ones served from the cache, and failed ones) adds a row to a private Google
Sheet in your own Google account:

| Time | Name | Email | PDB ID | Style | Colour | … all options | Status | From cache | Render time (s) | Error | Open again |
|---|---|---|---|---|---|---|---|---|---|---|---|

*Open again* is a link that reopens the site with the same settings, so you can see any
image a person made without storing images anywhere. Names and emails are never shown to
other visitors or put in shared links. Nothing checks that an email address is real.

Set it up once, in about 10 minutes:

1. Create a new Google Sheet (any name), for example at <https://sheets.new>.
2. In the Sheet, open **Extensions → Apps Script**. Delete what is in the editor, paste in
   the whole of [`google-sheet/Code.gs`](google-sheet/Code.gs), and replace `CHANGE-ME` in
   the `TOKEN` line with a long random password of your choice. Click **Save**.
3. Click **Deploy → New deployment**. Next to "Select type" click the gear icon and choose
   **Web app**. Set **Execute as: Me** and **Who has access: Anyone**, then click **Deploy**.
4. Google asks you to authorise the script. Choose your account; on the "Google hasn't
   verified this app" screen click **Advanced → Go to … (unsafe)**. This warning appears
   for every personal script, and the script only touches this one Sheet.
5. Copy the **Web app URL** (it ends in `/exec`). To check it, open it in a browser: it
   should say *"Render the Molecule recorder is running"*.
6. In your Hugging Face Space, open **Settings → Variables and secrets** and add two
   **secrets**: `SHEET_WEBHOOK_URL` = the Web app URL, and `SHEET_TOKEN` = the same
   password as in step 2. The Space restarts. A "Renders" tab with a header row appears in
   the Sheet after the first render.

If you later change the script, use **Deploy → Manage deployments → Edit → Version: New
version**, or Google keeps serving the old code. If the Sheet cannot be reached, the app
keeps rendering and retries sending the rows (they are lost only if the Space restarts
before the Sheet is reachable again). The Space logs say why a send failed, for example
a wrong token.

Because the site records personal data, keep the Sheet private and delete a person's rows
if they ask you to.

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
| `SHEET_WEBHOOK_URL` | (none) | Google Apps Script web app URL for the record of renders |
| `SHEET_TOKEN` | (none) | Password shared with the Apps Script (`TOKEN` in `Code.gs`) |
| `PUBLIC_URL` | `https://$SPACE_HOST` | Site address used in the "Open again" links |

## API

* `POST /api/render` with JSON such as `{"pdb_id": "4HHB", "style": "surface", "name": "Ada Lovelace", "email": "ada@example.org"}` returns a job (HTTP 202).
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

## Credits and how to cite

Render the Molecule was developed by **Vishal Bhoir**
(ORCID [0009-0004-8803-1967](https://orcid.org/0009-0004-8803-1967)). Images are made with
[Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) by Brady Johnston and
contributors and with [Blender](https://www.blender.org); structures come from the
[RCSB Protein Data Bank](https://www.rcsb.org).

Every image carries its credits in two ways:

* **A small credit line** in the bottom-right corner, for example
  *"PDB 4HHB · Molecular Nodes · Render the Molecule by Vishal Bhoir"*. It is on by default;
  untick *Credit line on the image* under *More options* for a clean figure, and cite in the
  text instead.
* **PNG metadata** (always): title, software and versions, source entry, and the citation text
  below. Image viewers show it under file information.

After each render the page shows a **"How to cite this image"** box with a copy button. For
PDB entry 4HHB it reads:

> The structure of PDB entry 4HHB was rendered with Render the Molecule (v0.1.0; Bhoir, 2026)
> using Molecular Nodes (v520.2.0; Johnston et al.) and Blender (v5.2.2); structure data from
> the RCSB Protein Data Bank (Berman et al., 2000).

References (APA 7th):

1. Bhoir, V. (2026). *Render the Molecule* (Version 0.1.0) [Web application]. https://github.com/vishalbhoir18/renderthemolecule
2. Johnston, B., & Molecular Nodes contributors. (2026). *Molecular Nodes* (Version 520.2.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22827864
3. Blender Online Community. (2026). *Blender* (Version 5.2.2) [Computer software]. Blender Foundation. https://www.blender.org
4. Berman, H. M., Westbrook, J., Feng, Z., Gilliland, G., Bhat, T. N., Weissig, H., Shindyalov, I. N., & Bourne, P. E. (2000). The Protein Data Bank. *Nucleic Acids Research, 28*(1), 235–242. https://doi.org/10.1093/nar/28.1.235
5. The primary publication of the PDB entry, listed on its RCSB page (e.g. https://www.rcsb.org/structure/4HHB).

Molecular Nodes has no paper yet; its authors ask to be cited through its Zenodo record.
The page's own box uses the address of the live site in reference 1. GitHub's **"Cite this
repository"** button (from `CITATION.cff`) gives the same reference in APA and BibTeX.

**Giving this tool its own DOI.** Archive a release on [Zenodo](https://zenodo.org):

1. Sign in to Zenodo with your GitHub account, open **Settings → GitHub**, and switch on
   `vishalbhoir18/renderthemolecule` (the repository must be public).
2. On GitHub, create a release (for example tag `v0.1.0`). Zenodo archives it within a few
   minutes and issues two DOIs: one for this version and a *concept* DOI for all versions.
3. Put the DOI in `APP_DOI` in `app/about.py` and as `doi:` in `CITATION.cff`, and add the
   Zenodo DOI badge to this README. Every citation box and image then shows it.

When a paper about the tool is published, cite the paper instead and keep the Zenodo DOI for
the exact software version.

## Licence

Copyright (C) 2026 Vishal Bhoir.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version. It is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See [`LICENSE`](LICENSE) for the full text.

It builds on Molecular Nodes (GPL-3.0) and Blender (GPL). Structure data from the PDB is free
of usage restrictions, but please cite the entries you render.
