"""In-process job queue: one worker thread renders one job at a time.

A free Hugging Face Space is a single container, so there is no Redis/Celery:
the queue lives in memory. If the Space restarts, queued jobs are lost (the
page tells the visitor to resubmit) but finished images on disk are reused.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .errors import QueueFull, TooManyJobs, UserError
from .options import RenderRequest
from .renderer import RenderFn
from .storage import prune_directory

log = logging.getLogger(__name__)

GENERIC_ERROR = "Something went wrong while rendering. Please try again."


def _mark_used(path: Path) -> bool:
    """Refresh a cached file's age for LRU pruning; False if it does not exist.

    Unlike Path.touch(), this never creates an empty file if the pruner
    deleted it a moment ago.
    """
    try:
        os.utime(path)
        return True
    except FileNotFoundError:
        return False


@dataclass(eq=False)
class Job:
    request: RenderRequest
    key: str
    client: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"  # queued | running | done | failed
    stage: str | None = None  # downloading | rendering (while running)
    error: str | None = None
    cached: bool = False
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


class JobManager:
    def __init__(self, settings: Settings, render_fn: RenderFn):
        self.settings = settings
        self._render_fn = render_fn
        self._cv = threading.Condition()
        self._queue: deque[Job] = deque()
        self._jobs: dict[str, Job] = {}
        self._active_by_key: dict[str, Job] = {}
        self._running: Job | None = None
        self._stopping = False
        self._thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.settings.ensure_dirs()
        self._thread = threading.Thread(target=self._work, name="render-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        with self._cv:
            self._stopping = True
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout)

    # ---- public API ------------------------------------------------------
    def output_path(self, key: str) -> Path:
        return self.settings.renders_dir / f"{key}.png"

    def submit(self, request: RenderRequest, client: str) -> Job:
        key = request.cache_key()
        with self._cv:
            self._forget_old_jobs()

            if _mark_used(self.output_path(key)):
                now = time.time()
                job = Job(request, key, client, status="done", cached=True,
                          started_at=now, finished_at=now)
                self._jobs[job.id] = job
                return job

            # Same picture already on its way: share that job.
            existing = self._active_by_key.get(key)
            if existing is not None:
                return existing

            if len(self._queue) >= self.settings.max_queue:
                raise QueueFull
            mine = sum(1 for j in self._active_by_key.values() if j.client == client)
            if mine >= self.settings.max_active_per_client:
                raise TooManyJobs

            job = Job(request, key, client)
            self._jobs[job.id] = job
            self._active_by_key[key] = job
            self._queue.append(job)
            self._cv.notify()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._cv:
            return self._jobs.get(job_id)

    def snapshot(self, job: Job) -> dict:
        """A consistent, JSON-ready view of a job."""
        with self._cv:
            ahead = None
            if job.status == "queued":
                try:
                    ahead = self._queue.index(job) + (1 if self._running else 0)
                except ValueError:
                    ahead = 0
            now = time.time()
            return {
                "id": job.id,
                "status": job.status,
                "stage": job.stage,
                "pdb_id": job.request.pdb_id,
                "jobs_ahead": ahead,
                "error": job.error,
                "cached": job.cached,
                "image_url": f"/renders/{job.key}.png" if job.status == "done" else None,
                "download_name": job.request.download_name(),
                "waited_s": round((job.started_at or now) - job.created_at, 1),
                "render_s": (
                    round((job.finished_at or now) - job.started_at, 1)
                    if job.started_at
                    else None
                ),
            }

    def stats(self) -> dict:
        with self._cv:
            return {"queued": len(self._queue), "running": self._running is not None}

    # ---- worker ----------------------------------------------------------
    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stopping:
                    self._cv.wait()
                if self._stopping:
                    return
                job = self._queue.popleft()
                job.status, job.started_at = "running", time.time()
                self._running = job

            def set_stage(stage: str, job: Job = job) -> None:
                with self._cv:
                    job.stage = stage

            status, error = "done", None
            try:
                self._render_fn(job.request, self.output_path(job.key), set_stage)
            except UserError as exc:
                status, error = "failed", str(exc)
            except Exception:
                log.exception("render job %s (%s) crashed", job.id, job.request.pdb_id)
                status, error = "failed", GENERIC_ERROR

            with self._cv:
                job.status, job.error, job.stage = status, error, None
                job.finished_at = time.time()
                self._running = None
                self._active_by_key.pop(job.key, None)

            self._prune_caches(keep=self.output_path(job.key))

    def _prune_caches(self, keep: Path) -> None:
        try:
            prune_directory(self.settings.renders_dir, self.settings.renders_cache_mb, keep=keep)
            prune_directory(self.settings.structures_dir, self.settings.structures_cache_mb)
        except OSError:
            log.exception("cache pruning failed")

    def _forget_old_jobs(self) -> None:
        cutoff = time.time() - self.settings.job_ttl
        for job_id, job in list(self._jobs.items()):
            if not job.active and (job.finished_at or 0) < cutoff:
                del self._jobs[job_id]
