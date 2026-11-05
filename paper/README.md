# Manuscript: Render the Molecule

Draft research article describing and benchmarking Render the Molecule.

| File | What it is |
| --- | --- |
| `manuscript.md`, `manuscript.docx`, `manuscript.pdf` | The manuscript (Markdown working copy, Word file for submission, PDF preview) |
| `figures/` | Figure files: 1 request flow, 2 representations and colour schemes, 3 time and memory against size, 4 gallery, 5 image quality, S1 sample-budget crops (PNG; PDF for the plots) |
| `references.md` | The reference list (APA 7); every journal DOI was checked against Crossref |
| `reference_dois.txt`, `verify_references.py`, `build_references.py`, `references_crossref.md` | DOI list, the Crossref check, and the raw Crossref-generated entries |
| `benchmark/run_benchmark.py` | Renders the ten-entry panel through the app's own code (experiments E1 to E7) |
| `benchmark/results.csv` | One row per render: timings, peak memory, status |
| `benchmark/analyse.py`, `benchmark/summary.json` | Image-quality metrics (SSIM, PSNR), repeatability, figure generation |
| `benchmark/chart_rows.py` | Prints the rows the manuscript's charts are drawn from |
| `benchmark/pdb_size_distribution.py`, `benchmark/pdb_atom_counts.csv` | Deposited atom counts of all current PDB entries (RCSB Data API) |

## Reproduce the benchmark

Linux x86-64, Python 3.13, the system libraries listed in the repository's `Dockerfile`, and network access to `models.rcsb.org`:

```bash
pip install -r requirements-dev.txt
```

```bash
python paper/benchmark/run_benchmark.py
```

```bash
python paper/benchmark/analyse.py
```

The full run (63 render attempts, 60 images) took about an hour on 4 vCPUs and needs about 15 GB of memory for the largest entries. The 60 images are written to `paper/benchmark/renders/` (git-ignored, 25 MB).
