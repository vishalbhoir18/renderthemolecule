"""Download structures from the PDB and keep the on-disk caches bounded."""

from __future__ import annotations

import gzip
import logging
import os
import tempfile
from pathlib import Path

import requests

from .config import Settings
from .errors import UserError

log = logging.getLogger(__name__)

_GZIP_MAGIC = b"\x1f\x8b"


def fetch_structure(code: str, settings: Settings) -> Path:
    """Return a local BinaryCIF file for ``code``, downloading it if needed."""
    dest = settings.structures_dir / f"{code}.bcif"
    try:
        os.utime(dest)  # mark as recently used for pruning; never creates a file
        return dest
    except FileNotFoundError:
        pass

    url = settings.structure_url.format(code=code)
    limit = settings.max_download_mb * 1024 * 1024
    try:
        with requests.get(url, stream=True, timeout=settings.download_timeout) as resp:
            if resp.status_code == 404:
                raise UserError(
                    f"{code.upper()} was not found in the Protein Data Bank. "
                    "Check the ID, or the entry may not be released yet."
                )
            if resp.status_code != 200:
                raise UserError(
                    f"The PDB download server answered with HTTP {resp.status_code}. "
                    "Please try again in a minute."
                )
            chunks, size = [], 0
            for chunk in resp.iter_content(chunk_size=1 << 20):
                size += len(chunk)
                if size > limit:
                    raise UserError(
                        f"{code.upper()} is larger than {settings.max_download_mb} MB, "
                        "too big for this free server."
                    )
                chunks.append(chunk)
    except requests.RequestException as exc:
        log.warning("download of %s failed: %s", url, exc)
        raise UserError(
            "Could not reach the PDB download server. Please try again in a minute."
        ) from exc

    content = b"".join(chunks)
    if content[:2] == _GZIP_MAGIC:
        content = gzip.decompress(content)
    if not content:
        raise UserError(f"The PDB returned an empty file for {code.upper()}.")

    # Write to a temp file first so a half-written file is never used.
    fd, tmp = tempfile.mkstemp(dir=settings.structures_dir, suffix=".part")
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    os.replace(tmp, dest)
    return dest


def prune_directory(directory: Path, max_mb: int, keep: Path | None = None) -> None:
    """Delete least recently used files until the directory fits in ``max_mb``."""
    files = [p for p in directory.iterdir() if p.is_file() and p != keep]
    total = sum(p.stat().st_size for p in files)
    if keep is not None and keep.exists():
        total += keep.stat().st_size
    limit = max_mb * 1024 * 1024
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= limit:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
        except FileNotFoundError:
            pass
