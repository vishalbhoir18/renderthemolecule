"""Settings, read from environment variables so the same image runs anywhere."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def available_cpus() -> int:
    """CPUs this container may actually use (cgroup quota aware).

    Blender sizes its thread pool from the host's CPU count, which on shared
    hosts (Hugging Face, Cloud Run) is far more than the container's quota and
    makes rendering slower, not faster.
    """
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return os.cpu_count() or 1


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path("data").absolute())
    # Where structures are downloaded from; {code} is the lower-case PDB ID.
    structure_url: str = "https://models.rcsb.org/{code}.bcif"
    download_timeout: int = 30  # seconds per network read
    max_download_mb: int = 200
    render_timeout: int = 600  # seconds before a render is killed
    render_threads: int = 0  # 0 = detect from the container's CPU quota
    max_queue: int = 20  # queued jobs (not counting the running one)
    max_active_per_client: int = 3  # queued + running jobs per visitor
    job_ttl: int = 3600  # seconds a finished job stays pollable
    renders_cache_mb: int = 2000
    structures_cache_mb: int = 2000
    # Atom limits (after expanding a biological assembly), by style.
    max_atoms_backbone: int = 3_000_000  # cartoon, ribbon
    max_atoms_atomic: int = 1_000_000  # surface, spheres
    max_atoms_bonds: int = 300_000  # ball_and_stick, sticks

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def structures_dir(self) -> Path:
        return self.data_dir / "structures"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    def ensure_dirs(self) -> None:
        for path in (self.renders_dir, self.structures_dir, self.work_dir):
            path.mkdir(parents=True, exist_ok=True)

    def threads(self) -> int:
        return self.render_threads or available_cpus()

    def max_atoms(self, style: str) -> int:
        if style in ("cartoon", "ribbon"):
            return self.max_atoms_backbone
        if style in ("ball_and_stick", "sticks"):
            return self.max_atoms_bonds
        return self.max_atoms_atomic

    @classmethod
    def from_env(cls) -> "Settings":
        base = cls()
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", base.data_dir)).absolute(),
            structure_url=os.environ.get("STRUCTURE_URL", base.structure_url),
            download_timeout=_env_int("DOWNLOAD_TIMEOUT", base.download_timeout),
            max_download_mb=_env_int("MAX_DOWNLOAD_MB", base.max_download_mb),
            render_timeout=_env_int("RENDER_TIMEOUT", base.render_timeout),
            render_threads=_env_int("RENDER_THREADS", base.render_threads),
            max_queue=_env_int("MAX_QUEUE", base.max_queue),
            max_active_per_client=_env_int(
                "MAX_ACTIVE_PER_CLIENT", base.max_active_per_client
            ),
            job_ttl=_env_int("JOB_TTL", base.job_ttl),
            renders_cache_mb=_env_int("RENDERS_CACHE_MB", base.renders_cache_mb),
            structures_cache_mb=_env_int(
                "STRUCTURES_CACHE_MB", base.structures_cache_mb
            ),
            max_atoms_backbone=_env_int("MAX_ATOMS_BACKBONE", base.max_atoms_backbone),
            max_atoms_atomic=_env_int("MAX_ATOMS_ATOMIC", base.max_atoms_atomic),
            max_atoms_bonds=_env_int("MAX_ATOMS_BONDS", base.max_atoms_bonds),
        )
