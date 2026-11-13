# Manuscript: Render the Molecule

Draft research article describing and benchmarking Render the Molecule version 0.2.0
(repository commit 12a84b1: Mol* 3D preview with "Render this view", shared colour-blind-safe
palettes, camera-relative lighting).

| File | What it is |
| --- | --- |
| `manuscript.md`, `manuscript.docx`, `manuscript.pdf` | The manuscript (Markdown working copy, Word file for submission, PDF preview) |
| `figures/` | 1 request flow, 2 representations and colour schemes, 3 time and memory against size, 4 gallery, 5 image quality, 6 preview against render, S1 sample-budget crops (PNG; PDF for the plots; WebP copies) |
| `references.md` | The reference list (APA 7); every journal DOI was checked against Crossref |
| `reference_dois.txt`, `verify_references.py`, `build_references.py`, `references_crossref.md` | DOI list, the Crossref check, and the raw Crossref-generated entries |
| `build_manuscript_files.py` | Turns the editable manuscript's Markdown and Word exports into the files above |
| `benchmark/run_benchmark.py` | Renders the benchmark through the app's own code (experiments E1 to E8) |
| `benchmark/capture_previews.js` | Captures the Mol* preview and its camera for experiment E8 (Playwright) |
| `benchmark/preview/` | The captured previews and `cameras.json` |
| `benchmark/results.csv`, `benchmark/run_info.json` | One row per render (timings, peak memory, status); the commit, versions and hardware benchmarked |
| `benchmark/analyse.py`, `benchmark/summary.json` | Image quality (SSIM, PSNR), repeatability, preview agreement, and the figures |
| `benchmark/chart_rows.py` | Prints the rows the manuscript's charts are drawn from |
| `benchmark/pdb_size_distribution.py`, `benchmark/pdb_atom_counts.csv` | Deposited atom counts of all current PDB entries (RCSB Data API) |
| `benchmark/v0.1.0/` | Results of the first benchmark, of version 0.1.0 on a different machine |

## Reproduce the benchmark

Linux x86-64, Python 3.13, the system libraries listed in the repository's `Dockerfile`, and network
access to `models.rcsb.org`. Experiment E8 also needs Node.js with Playwright and the app running
locally (no Google Sheet is configured, so nothing is recorded):

```bash
pip install -r requirements-dev.txt
```

```bash
uvicorn --factory app.main:create_app --port 7861
```

```bash
node paper/benchmark/capture_previews.js http://localhost:7861 paper/benchmark/preview
```

Stop the server, then:

```bash
python paper/benchmark/run_benchmark.py
```

```bash
python paper/benchmark/analyse.py
```

The full run (71 renders) took about 75 minutes on 4 vCPUs at 2.10 GHz. The HIV-1 capsid cartoon
(3J3Q) peaks at about 12.5 GB of memory, so the machine needs about 16 GB. The images are written to
`paper/benchmark/renders/` (git-ignored).
