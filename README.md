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

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23960655.svg)](https://doi.org/10.5281/zenodo.23960655)

Type a Protein Data Bank ID (for example `4HHB`) and get a publication-quality
image back, rendered by [Blender](https://www.blender.org) with the
[Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) add-on.
No Blender installation is needed on the visitor's side; everything runs on the server.

Options: style (cartoon, ribbon, surface, spheres, ball-and-stick, sticks),
colour (by chain, rainbow, secondary structure, Goodsell), material, viewpoint,
image size, quality, white/black/transparent background, ligand highlighting
and biological assemblies. An interactive 3D preview ([Mol*](https://molstar.org)) shows the
molecule as soon as an ID is typed: turn and zoom it, and **Render this view** makes Blender
render exactly that view. Visitors give their name and email, and every render
can be recorded in a private Google Sheet (see below). Each image credits its
sources and comes with a ready-made citation.

Developed by **Vishal Bhoir** ([ORCID 0009-0004-8803-1967](https://orcid.org/0009-0004-8803-1967)).
Free software under the GNU GPL v3 or later.

## Use it

* **Web app:** <https://vishalbhoir18--render-the-molecule.us-east.modal.run>
* **Google Colab** (free, runs on your own Google session):
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/vishalbhoir18/renderthemolecule/blob/main/notebooks/render_the_molecule.ipynb)
* **Landing page:** <https://vishalbhoir18.github.io/renderthemolecule/>
* **Command line** (Linux x86-64, Python 3.13, after `pip install -r requirements.txt`):
  `python -m app.cli --pdb-id 4HHB --name "Your Name" --email you@example.org --institution "Your University" --country India --out results`
  (`--help` lists every option).

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
* **Lighting.** Three sun lights are placed relative to the camera, as Mol*'s light is (key
  from the upper left, fill from the right, rim from behind), so every view, including one
  chosen in the 3D preview, is lit alike. The default material is *Glossy (lit)*; *Ambient
  occlusion* is evenly self-lit and looks flatter. Colours go through Blender's
  "Khronos PBR Neutral" view transform, which keeps them as chosen (the default, AgX, turns
  strong colours pastel). The settings are `LIGHTS`, `WORLD_STRENGTH`, `GLOSSY_ROUGHNESS` and
  `VIEW_TRANSFORM` in `app/blender_render.py`.
* **One process per render.** Blender keeps global state and can crash; a fresh process per job
  keeps the web server alive and returns all memory after every render.
* **No Redis/Celery.** The app runs as a single container (on Modal or any Docker host), so the queue lives in
  memory. One worker is right anyway: Cycles already uses every CPU core.
* **Content-addressed cache.** Each image is named by a hash of its options, so a repeated
  request (or a shared link) is served instantly.

### 3D preview and "Render this view"

The page loads [Mol*](https://molstar.org) (MIT licence; the viewer build is in
`app/static/vendor/molstar`, served by the app itself) the first time a PDB ID is entered. The
structure comes from `GET /api/structure/{id}`, the same download cache the renders use, so
the browser contacts no other site and the render that follows does not download it again.
`app/static/preview.js` mirrors the chosen style, colour, ligands, assembly and background,
keeps the viewer at the image's aspect ratio, and shows the selected preset view as Blender
frames it.

**Save preview image** downloads the Mol* view as a PNG at the chosen image size and
background, with a credit line naming Mol* if that option is ticked. It is made in the
visitor's browser, so it is instant, uses no server time and is not recorded in the Sheet.
The page asks people who publish one to cite Mol* (Sehnal et al., 2021,
<https://doi.org/10.1093/nar/gkab314>), this tool and the PDB entry; **Render image** stays the
publication-quality step.

Turning or zooming the molecule ticks **Render this view**. The camera is then sent with the
request as `camera`: position, target and up direction in ångström, in the structure file's
coordinates, and the vertical field of view in degrees. Both programs keep those coordinates
(Molecular Nodes scales them by 0.1), so `place_camera` in `app/blender_render.py` sets the
Blender camera directly: same position and orientation, vertical sensor fit, same vertical
angle. Values are rounded (0.01 Å, 4 decimals for the direction), so the same view gives the
same cache key. The view is part of the shareable link (`cam=`), the Sheet's *View* column says
"3D preview", and the command line accepts it as `--camera` (the same 10 numbers).
`tests/test_render_smoke.py` checks with a real render that the molecule lands where the
camera puts it.

**Preset views.** While **Render this view** is off, no camera is sent and Blender frames the
molecule with Molecular Nodes' `canvas.look_at`: the camera turns to the preset direction and,
with Blender's 50 mm lens (39.6° across the image's longer side), moves as close as it can
while every point of the drawn geometry stays inside the frame less a 5% margin.
`app/static/framing.js` runs the same solve on what Mol* draws (mesh vertices, and sphere
centres grown by their radius, as Molecular Nodes grows its spheres) with the same field of
view, so the preview shows a preset view as it will be rendered. The request stays a preset:
its cache key, share link and the Sheet's *View* column are the same as from the API or the
command line. `tests/test_preview_framing.py` checks the solve against Molecular Nodes in
Blender.

The preview is approximate in looks (Mol*'s own cartoon and lighting), not in framing or
colour.

**Colours.** Both programs colour the same way, from constants in `app/options.py` that the
page reads from `/api/options`:

* *By chain*: chains take `CHAIN_COLORS` in the order of their IDs (A, B, C, ...), repeating
  after the last. It is the colour-blind-safe Okabe-Ito palette (Wong, *Nature Methods* 8, 441;
  2011). Spheres and sticks show other elements in their usual colours.
* *Goodsell*: each chain in its colour, with carbon atoms darkened (visible on spheres, sticks
  and surfaces; a cartoon has no atoms to darken).
* *Rainbow*: blue to red along each chain's protein or nucleic acid, by residue number
  (`RAINBOW_COLORS`); ligands and water grey.
* *Secondary structure*: Molecular Nodes' colours, helices green, sheets red, loops blue.

`app/blender_render.py` stores the chain and rainbow colours as per-atom attributes, converted
to Blender's linear colour space; `app/static/preview.js` gives Mol* the same colours (its
rainbow is a small custom colour theme). Changing a palette changes both.

Measured on a 4-vCPU machine at 1280 × 720: 15–23 s per image at *Standard* quality and about
9 s at *Draft*, plus 3–4 s of scene setup. With 2 threads, the same renders took 45–140 s.

## Deploy on Modal

[Modal](https://modal.com) runs the app in a container that starts when someone visits and
stops 5 minutes after the last request, so you use credits only while the site is in use.
`modal_app.py` describes the deployment: the same base image, libraries and pinned packages
as the `Dockerfile` (which CI builds and tests), 2 CPU cores, 8 GB memory, and a single
container (the job queue lives in its memory).

**Cost.** A new account gets **$1** of credit without a card; adding a card unlocks
**$30 per month**. By my estimate from Modal's published rates, the container costs about
$0.16 per hour while it is running, so a visit costs about 1–2 cents. Credits run out at
roughly 6 hours of use on the $1, or about 190 hours a month on the $30 (estimates, not
measurements). **To never be charged**, open **Usage & Billing** in Modal and set a
**spend limit** as low as it allows (ideally $0): when credits run out, Modal stops the app
instead of billing you, and the site comes back with next month's credits.

**Deploy from GitHub (no software on your computer):**

1. Sign up at <https://modal.com> (choose *Personal*, *Other*, *Get started*).
2. In Modal, open **Settings → API Tokens → New Token** and copy the token ID and secret.
3. In this GitHub repository, open **Settings → Secrets and variables → Actions**:
   * **Secrets** tab: add `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. If you have set up the
     Google Sheet (next section), also add `SHEET_WEBHOOK_URL` and `SHEET_TOKEN`.
   * **Variables** tab: add `MODAL_DEPLOY` with the value `true`.
4. Open the **Actions** tab → **CI** → **Run workflow**, choose the branch, and run it. When the
   *deploy-modal* job finishes (the first build takes several minutes), its log shows the
   address, for example `https://vishalbhoir18--render-the-molecule.us-east.modal.run`.

After that, every push to `main` redeploys automatically. Run the workflow again whenever
you change the Sheet secrets.

**Or deploy from your computer** (Python 3.10 or newer):

```bash
pip install "modal==1.6.3"
```

```bash
modal setup
```

```bash
modal deploy modal_app.py
```

To turn on the Sheet record this way, set `SHEET_WEBHOOK_URL` and `SHEET_TOKEN` in your
terminal before `modal deploy`; they are passed to the app as a Modal secret.

**Things to know.** The first visitor after a quiet period waits for the container to start
(usually under a minute). Images are kept only while the container is up; afterwards the
same request simply renders again. The **Apps** page in Modal shows the app, its logs and
its cost so far; **Stop app** takes the site offline.

## Alternative: Hugging Face Spaces (needs PRO)

Since July 2026, Docker Spaces need a Hugging Face **PRO** account (about $9 a month); free
accounts can create only static Spaces. With PRO:

1. Click **New Space**, choose **Docker** → **Blank** and hardware **CPU basic**.
2. Create an access token with **write** permission (Settings → Access Tokens).
3. Push this repository to the Space; use the token as the password when asked:

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
   ```

   ```bash
   git push space main
   ```

The app is then at `https://<your-username>-<space-name>.hf.space`. For automatic deploys,
add a GitHub secret `HF_TOKEN` and variable `HF_SPACE` (`<your-username>/<space-name>`);
pushes to `main` that pass CI are then deployed. For the Sheet record, add
`SHEET_WEBHOOK_URL` and `SHEET_TOKEN` as **secrets** in the Space settings.

## Record who rendered what in a Google Sheet

Visitors must enter their **name, email, institution and country** before rendering. Each finished request
(including ones served from the cache, and failed ones) adds a row to a private Google
Sheet in your own Google account:

| Time | Name | Email | PDB ID | Style | Colour | … all options | Status | From cache | Render time (s) | Error | Open again | Source | Institution | Country |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

*Source* is **Web app** or **Colab** (renders made with the Colab notebook).

*Open again* is a link that reopens the site with the same settings, so you can see any
image a person made without storing images anywhere. Names and emails are never shown to
other visitors or put in shared links. Nothing checks that an email address is real.

Set it up once, in about 10 minutes:

1. Create a new Google Sheet (any name), for example at <https://sheets.new>.
2. In the Sheet, open **Extensions → Apps Script**. Delete what is in the editor, paste in
   the whole of [`google-sheet/Code.gs`](google-sheet/Code.gs). Replace `CHANGE-ME` in the
   `TOKEN` line with a long random password of your choice (the website's private password),
   and `CHANGE-ME-COLAB` in the `COLAB_TOKEN` line with a *different* random value (the
   notebook's public key). Click **Save**.
3. Click **Deploy → New deployment**. Next to "Select type" click the gear icon and choose
   **Web app**. Set **Execute as: Me** and **Who has access: Anyone**, then click **Deploy**.
4. Google asks you to authorise the script. Choose your account; on the "Google hasn't
   verified this app" screen click **Advanced → Go to … (unsafe)**. This warning appears
   for every personal script, and the script only touches this one Sheet.
5. Copy the **Web app URL** (it ends in `/exec`). To check it, open it in a browser: it
   should say *"Render the Molecule recorder is running"*.
6. Give the app two settings: `SHEET_WEBHOOK_URL` = the Web app URL, and `SHEET_TOKEN` = the
   same password as in step 2. On Modal, add them as GitHub **secrets** and run the deploy
   workflow again (see "Deploy on Modal"). A "Renders" tab with a header row appears in the
   Sheet after the first render.
7. For the Colab notebook, edit [`notebooks/colab_recording.json`](notebooks/colab_recording.json)
   on GitHub (pencil icon): put the Web app URL in `url` and the `COLAB_TOKEN` value in `key`,
   then commit to `main`.

**About the Colab key.** It is public: anyone who reads the notebook can see it. The script
therefore marks every row sent with it as *Colab* and accepts at most 3 rows per request, so
it cannot fake website rows. If it is ever abused, change `COLAB_TOKEN` in the script (and
deploy a new version) and in `colab_recording.json`; the website is not affected. Colab users
run their own copy of the notebook, so recording there relies on their honesty.

**Updating the script** (whenever `Code.gs` changes, for example when the *Source*,
*Institution* and *Country* columns were added): paste the new `Code.gs`, put your existing
values back into `TOKEN` and `COLAB_TOKEN`, then **Deploy → Manage deployments → Edit →
Version: New version → Deploy** (the URL stays the same). Existing rows are kept; new
columns are always added at the end and their headers appear automatically.

If you later change the script, use **Deploy → Manage deployments → Edit → Version: New
version**, or Google keeps serving the old code. If the Sheet cannot be reached, the app
keeps rendering and retries sending the rows (they are lost only if the Space restarts
before the Sheet is reachable again). The app's logs say why a send failed, for example
a wrong token.

### Privacy notice

The details are covered by a short privacy notice: [`app/static/privacy.html`](app/static/privacy.html),
served by the web app at `/privacy` and copied to [`docs/privacy.html`](docs/privacy.html) for the
landing page (a test keeps the two identical). It is linked next to the form fields, in the web app's
footer, on the landing page and in the notebook, and its key sentence is shown wherever details
are asked for:

> Your information will be used to understand academic adoption and improve the application.
> It will not be shared or used for marketing without your separate consent.

Keep the Sheet private, and delete a person's rows if they ask you to. The notice points
people to <https://linktr.ee/thebioway> for such requests; to give an email address instead,
change the *Your choices* paragraph of both copies.

**Journals.** The NAR Web Server Issue does not accept tools that force users to register, log
in or enter an email address. Before submitting there, make the details optional.

## Google Colab notebook and landing page

* [`notebooks/render_the_molecule.ipynb`](notebooks/render_the_molecule.ipynb) installs Blender
  and Molecular Nodes in the visitor's own Colab session, renders with the same code as the web
  app (`app/cli.py`), shows the image and its citation, and records the render (see above). It
  is generated by `notebooks/build_notebook.py` from the app's own option lists; run that
  script after changing options, and the tests check the two stay in step.
* [`docs/index.html`](docs/index.html) is a static landing page linking to the web app and the
  notebook. To publish it with GitHub Pages: **Settings → Pages → Build and deployment →
  Source: Deploy from a branch → Branch: `main`, folder `/docs` → Save**. It appears at
  <https://vishalbhoir18.github.io/renderthemolecule/> a minute later.

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

* `POST /api/render` with JSON such as `{"pdb_id": "4HHB", "style": "surface", "name": "Ada Lovelace", "email": "ada@example.org", "institution": "University of London", "country": "United Kingdom"}` returns a job (HTTP 202).
  An optional `"camera": {"position": [x, y, z], "target": [x, y, z], "up": [x, y, z], "fov": 45}`
  (ångström, structure-file coordinates; vertical field of view in degrees) renders that exact view.
* `GET /api/structure/{id}` returns the entry's BinaryCIF file from the server's cache (used by the 3D preview).
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

> The structure of PDB entry 4HHB was rendered with Render the Molecule (v0.2.0; Bhoir, 2026)
> using Molecular Nodes (v520.2.0; Johnston et al.) and Blender (v5.2.2); structure data from
> the RCSB Protein Data Bank (Berman et al., 2000).

References (APA 7th):

1. Bhoir, V. (2026). *Render the Molecule* (Version 0.2.0) [Web application]. Zenodo. https://doi.org/10.5281/zenodo.23960655
2. Johnston, B., & Molecular Nodes contributors. (2026). *Molecular Nodes* (Version 520.2.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22827864
3. Blender Online Community. (2026). *Blender* (Version 5.2.2) [Computer software]. Blender Foundation. https://www.blender.org
4. Berman, H. M., Westbrook, J., Feng, Z., Gilliland, G., Bhat, T. N., Weissig, H., Shindyalov, I. N., & Bourne, P. E. (2000). The Protein Data Bank. *Nucleic Acids Research, 28*(1), 235–242. https://doi.org/10.1093/nar/28.1.235
5. The primary publication of the PDB entry, listed on its RCSB page (e.g. https://www.rcsb.org/structure/4HHB).

Molecular Nodes has no paper yet; its authors ask to be cited through its Zenodo record.
The page's own box uses the address of the live site in reference 1. GitHub's **"Cite this
repository"** button (from `CITATION.cff`) gives the same reference in APA and BibTeX.

**DOI.** Every GitHub release is archived on Zenodo, which gives it its own DOI. The tool is cited
with the *concept DOI* https://doi.org/10.5281/zenodo.23960655 ("cite all versions"), which always
resolves to the latest release, together with the exact version number from `APP_VERSION`; the
app, the badge above, the footer, the landing page and the notebook all use it, so none of them
change from release to release. Version 0.2.0 is https://doi.org/10.5281/zenodo.24221994.

To make a release:

1. Bump `APP_VERSION` in `app/about.py`, and `version:` and `date-released:` in `CITATION.cff`,
   so that the archived code already reports the new version. Bump `RENDER_VERSION` in
   `app/options.py` too, so cached images with the old version in their metadata are not reused.
   Merge this into `main`.
2. On GitHub, open **Releases → Draft a new release**, create the tag (for example `v0.3.0`) on
   `main`, and publish it. Zenodo archives it within minutes.
3. Optionally, list the new version's own DOI under `identifiers:` in `CITATION.cff` and next to
   the concept DOI in `app/about.py`.

When a paper about the tool is published, cite the paper instead and keep the Zenodo DOI for
the exact software version.

## Licence

Copyright (C) 2026 Vishal Bhoir.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version. It is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See [`LICENSE`](LICENSE) for the full text.

It builds on Molecular Nodes (GPL-3.0) and Blender (GPL). The 3D preview ships the Mol* viewer
(MIT licence, copyright Mol* contributors; `app/static/vendor/molstar/LICENSE`). Structure data
from the PDB is free of usage restrictions, but please cite the entries you render.
