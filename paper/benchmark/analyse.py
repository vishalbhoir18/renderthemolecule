"""Summarise paper/benchmark/results.csv and build the manuscript figures.

    python paper/benchmark/analyse.py

Writes paper/benchmark/summary.json, image-quality and repeatability tables,
and figure files to paper/figures/.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIG = ROOT / "paper" / "figures"
CREDIT_FRACTION = 0.06  # bottom rows holding the (identical) credit line


def rows() -> list[dict]:
    with open(HERE / "results.csv") as fh:
        return list(csv.DictReader(fh))


def luminance(path: Path) -> np.ndarray:
    img = Image.open(ROOT / path).convert("RGB")
    a = np.asarray(img, dtype=np.float64)
    y = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return y[: int(round(y.shape[0] * (1 - CREDIT_FRACTION)))]


def ssim(x: np.ndarray, y: np.ndarray, data_range: float = 255.0, mask=None) -> float:
    """Mean SSIM (Wang et al., 2004): Gaussian window sigma 1.5, K1 0.01, K2 0.03.

    With ``mask``, the SSIM map is averaged over the masked pixels only.
    """
    c1, c2 = (0.01 * data_range) ** 2, (0.03 * data_range) ** 2
    blur = lambda a: gaussian_filter(a, 1.5, truncate=3.5)  # noqa: E731
    mx, my = blur(x), blur(y)
    sxx = blur(x * x) - mx * mx
    syy = blur(y * y) - my * my
    sxy = blur(x * y) - mx * my
    s = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))
    return float(s[mask].mean() if mask is not None else s.mean())


def foreground(ref: np.ndarray) -> np.ndarray:
    """Pixels of the molecule: not white background in the reference, grown by 4 px."""
    from scipy.ndimage import binary_dilation
    return binary_dilation(ref < 250, iterations=4)


def psnr(x: np.ndarray, y: np.ndarray, mask=None) -> float:
    d = (x - y) if mask is None else (x - y)[mask]
    mse = float(np.mean(d ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255.0**2 / mse)


def image_quality(data: list[dict]) -> list[dict]:
    out = []
    e3 = [r for r in data if r["experiment"] == "E3" and r["status"] == "ok"]
    for pdb, style in (("4HHB", "cartoon"), ("1AON", "surface")):
        group = [r for r in e3 if r["pdb_id"] == pdb and r["style"] == style]
        ref = next((r for r in group if r["quality"] == "reference"), None)
        if ref is None:
            continue
        y_ref = luminance(ref["image"])
        fg = foreground(y_ref)
        for r in sorted(group, key=lambda r: int(r["samples"])):
            y = luminance(r["image"])
            out.append({
                "pdb_id": pdb, "style": style, "quality": r["quality"],
                "samples": int(r["samples"]), "render_s": float(r["render_s"]),
                "wall_s": float(r["wall_s"]),
                "ssim": round(ssim(y, y_ref), 4),
                "psnr_db": round(psnr(y, y_ref), 2) if r is not ref else None,
                "foreground_fraction": round(float(fg.mean()), 3),
                "ssim_fg": round(ssim(y, y_ref, mask=fg), 4),
                "psnr_fg_db": round(psnr(y, y_ref, mask=fg), 2) if r is not ref else None,
            })
    return out


def repeatability(data: list[dict]) -> dict:
    reps = [r for r in data if r["experiment"] == "E6" and r["status"] == "ok"]
    if len(reps) < 2:
        return {}
    a = np.asarray(Image.open(ROOT / reps[0]["image"]).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(ROOT / reps[1]["image"]).convert("RGB"), dtype=np.int16)
    diff = np.abs(a - b)
    same_bytes = (ROOT / reps[0]["image"]).read_bytes() == (ROOT / reps[1]["image"]).read_bytes()
    return {
        "identical_files": same_bytes,
        "max_abs_diff": int(diff.max()),
        "fraction_pixels_differing": round(float((diff.max(axis=2) > 0).mean()), 6),
        "mean_abs_diff": round(float(diff.mean()), 5),
        "render_s": [float(r["render_s"]) for r in reps],
    }


def label_font(size: int):
    return ImageFont.load_default(size=size)


def montage(items: list[tuple[str, str]], cols: int, tile_w: int, out: Path,
            crop_credit: bool = True) -> None:
    """Grid of renders with a letter and a caption under each tile."""
    tiles = []
    for path, caption in items:
        img = Image.open(ROOT / path).convert("RGB")
        if crop_credit:
            img = img.crop((0, 0, img.width, int(img.height * (1 - CREDIT_FRACTION))))
        img = img.resize((tile_w, round(img.height * tile_w / img.width)), Image.LANCZOS)
        tiles.append((img, caption))
    tile_h = max(t.height for t, _ in tiles)
    pad, cap_h = 12, 34
    rows_n = -(-len(tiles) // cols)
    sheet = Image.new("RGB", (cols * (tile_w + pad) + pad, rows_n * (tile_h + cap_h + pad) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (img, caption) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = pad + c * (tile_w + pad)
        y = pad + r * (tile_h + cap_h + pad)
        sheet.paste(img, (x, y))
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h - 1], outline=(215, 215, 215))
        letter = chr(ord("A") + i)
        draw.text((x + 8, y + 6), letter, fill=(30, 30, 30), font=label_font(26))
        draw.text((x, y + tile_h + 6), caption, fill=(40, 40, 40), font=label_font(18))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    sheet.save(out.with_suffix(".webp"), quality=88)


def find(data, **kw):
    for r in data:
        if all(r.get(k) == v for k, v in kw.items()) and r["status"] == "ok":
            return r["image"]
    return None


def build_figures(data: list[dict]) -> None:
    style_names = {"cartoon": "Cartoon", "ribbon": "Ribbon", "surface": "Surface",
                   "spheres": "Spheres", "ball_and_stick": "Ball and stick", "sticks": "Sticks"}
    items = []
    for s, label in style_names.items():
        p = find(data, experiment="E2", style=s, color="default")
        if p:
            items.append((p, f"{label}, by chain"))
    for st, c, label in (("cartoon", "secondary_structure", "Cartoon, secondary structure"),
                         ("cartoon", "rainbow", "Cartoon, rainbow"),
                         ("surface", "goodsell", "Surface, Goodsell")):
        p = find(data, experiment="E2", style=st, color=c)
        if p:
            items.append((p, label))
    if items:
        montage(items, 3, 520, FIG / "figure2_styles_4hhb.png", crop_credit=False)

    gallery = []
    for pdb, style, label in (
        ("1BNA", "cartoon", "1BNA B-DNA, cartoon"), ("1EHZ", "cartoon", "1EHZ tRNA, cartoon"),
        ("6VXX", "surface", "6VXX spike, surface"), ("1AON", "surface", "1AON GroEL-GroES, surface"),
        ("4UG0", "cartoon", "4UG0 80S ribosome, cartoon"), ("3J3Q", "cartoon", "3J3Q HIV-1 capsid, cartoon"),
    ):
        p = find(data, experiment="E1", pdb_id=pdb, style=style)
        if p:
            gallery.append((p, label))
    asm = find(data, experiment="E5", pdb_id="1CD3", style="surface", assembly="1")
    if asm:
        gallery.append((asm, "1CD3 phiX174 procapsid, 60-mer"))
    if gallery:
        montage(gallery, 3, 520, FIG / "figure4_gallery.png", crop_credit=False)


def plots(data: list[dict], quality: list[dict]) -> None:
    """Journal figures (PNG at 300 dpi and PDF) made with matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "font.family": "DejaVu Sans"})
    FIG.mkdir(parents=True, exist_ok=True)
    e1 = [r for r in data if r["experiment"] == "E1" and r["status"] == "ok"]
    fig, axes = plt.subplots(2, 1, figsize=(5.5, 5.6), sharex=True)
    series = {"cartoon": ("o", "#8C8C8C", 1.0), "surface": ("s", "#2A6FDB", 1.0),
              "spheres": ("^", "#BDBDBD", 1.0)}
    for style, (m, c, a) in series.items():
        pts = sorted((int(r["atoms_rendered"]), float(r["wall_s"]), float(r["peak_rss_mb"]) / 1024)
                     for r in e1 if r["style"] == style)
        if not pts:
            continue
        x, t, mem = zip(*pts)
        axes[0].plot(x, t, marker=m, color=c, alpha=a, label=style.capitalize(), lw=1.2, ms=4)
        axes[1].plot(x, mem, marker=m, color=c, alpha=a, label=style.capitalize(), lw=1.2, ms=4)
    killed = [r for r in data if r["experiment"] == "E1" and r["status"].startswith("crash")]
    for r in killed:
        axes[1].plot([2_440_800], [float(r["peak_rss_mb"]) / 1024], marker="x", color="black", ms=7)
        axes[1].annotate(f"{r['pdb_id']} cartoon: killed (out of memory)",
                         (2_440_800, float(r["peak_rss_mb"]) / 1024), xytext=(-8, 0),
                         textcoords="offset points", ha="right", va="center", fontsize=7.5)
    axes[1].axhline(8, color="#555555", ls="--", lw=0.8)
    axes[1].text(130, 8.3, "Public server memory (8 GB)", fontsize=7.5, color="#555555")
    axes[0].set_ylabel("Wall-clock time per image (s)")
    axes[1].set_ylabel("Peak memory (GB)")
    axes[1].set_xlabel("Atoms rendered (log scale)")
    axes[1].set_xscale("log")
    axes[1].set_xlim(100, 4e6)
    axes[0].set_ylim(0, 190)
    axes[1].set_ylim(0, 15)
    axes[1].xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v / 1e6:g}M" if v >= 1e6 else f"{v / 1e3:g}k" if v >= 1e3 else f"{v:g}"))
    axes[0].legend(frameon=False, loc="upper left")
    axes[0].set_title("A", loc="left", fontweight="bold")
    axes[1].set_title("B", loc="left", fontweight="bold")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"figure3_scaling.{ext}", dpi=300)
    plt.close(fig)

    if quality:
        fig, ax = plt.subplots(figsize=(3.5, 3.0))
        for (pdb, style), c in ((("4HHB", "cartoon"), "#555555"), (("1AON", "surface"), "#AAAAAA")):
            pts = [(q["render_s"], q["psnr_fg_db"], q["samples"]) for q in quality
                   if q["pdb_id"] == pdb and q["quality"] != "reference"]
            if not pts:
                continue
            x, y, n = zip(*pts)
            ax.plot(x, y, marker="o", color=c, lw=1, label=f"{pdb} {style}")
            for xi, yi, ni in pts:
                if ni == 32:
                    ax.plot([xi], [yi], marker="o", color="#2A6FDB", ms=7, zorder=3)
                ax.annotate(f"{ni}", (xi, yi), textcoords="offset points", xytext=(6, 4), fontsize=7)
        ax.set_xlabel("Path-tracing time (s)")
        ax.set_ylabel("Foreground PSNR vs 512 samples (dB)")
        ax.set_ylim(39, 52)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        for ext in ("png", "pdf"):
            fig.savefig(FIG / f"figure5_quality.{ext}", dpi=300)
        plt.close(fig)


def sample_crops(data: list[dict]) -> None:
    """Supplementary Figure S1: the same 4HHB region at each sample budget, enlarged 2x."""
    e3 = [r for r in data if r["experiment"] == "E3" and r["status"] == "ok" and r["pdb_id"] == "4HHB"]
    if len(e3) < 4:
        return
    e3.sort(key=lambda r: int(r["samples"]))
    box = (700, 250, 1020, 430)  # a helix-rich region with a haem group, in 1280 x 720 pixels
    w, h = (box[2] - box[0]) * 2, (box[3] - box[1]) * 2
    pad, cap = 10, 30
    sheet = Image.new("RGB", (len(e3) * (w + pad) + pad, h + cap + 2 * pad), "white")
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(e3):
        crop = Image.open(ROOT / r["image"]).convert("RGB").crop(box).resize((w, h), Image.NEAREST)
        x = pad + i * (w + pad)
        sheet.paste(crop, (x, pad))
        label = f"{r['samples']} samples ({r['quality']}), {float(r['render_s']):.0f} s"
        draw.text((x, pad + h + 6), label, fill=(40, 40, 40), font=label_font(18))
    sheet.save(FIG / "figureS1_sample_crops.png", optimize=True)


def main() -> None:
    data = rows()
    summary = {
        "n_renders": len(data),
        "status_counts": {s: sum(r["status"] == s for r in data) for s in sorted({r["status"] for r in data})},
        "image_quality": image_quality(data),
        "repeatability": repeatability(data),
    }
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2))
    build_figures(data)
    sample_crops(data)
    plots(data, summary["image_quality"])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
