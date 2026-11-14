"""HTTP API and web page.

Run with:  uvicorn --factory app.main:create_app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import about
from .config import Settings
from .errors import QueueFull, TooManyJobs, UserError
from .jobs import Job, JobManager, Submitter
from .options import RenderRequest, Submission, option_lists
from .renderer import RenderFn, make_renderer
from .sheet import SheetRecorder, preview_row, record_row
from .storage import fetch_structure

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
RENDER_NAME_RE = re.compile(r"^[0-9a-f]{64}\.png$")
# Fields whose validation messages already say which field is wrong.
SELF_EXPLAINING_FIELDS = {"pdb_id", "name", "email", "institution", "country"}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class RateLimiter:
    """At most ``limit`` events per ``window`` seconds for each visitor."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._events) > 10_000:  # forget visitors who have been quiet for a while
                self._events = {k: v for k, v in self._events.items() if v and now - v[-1] < self.window}
            events = self._events.setdefault(client, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


# Preview images are made in the browser; recording them must not let anyone flood the Sheet.
PREVIEW_RECORDS_LIMIT = (30, 600)  # per visitor: 30 in 10 minutes


def _client_id(request: Request) -> str:
    # Behind the Hugging Face / Cloudflare proxy the visitor's address is in
    # X-Forwarded-For. It can be spoofed, so it only drives the per-visitor
    # limit; the global queue limit is what actually protects the server.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _base_url(request: Request, settings: Settings) -> str:
    if settings.public_url:
        return settings.public_url
    host = request.headers.get("host", request.url.netloc)
    proto = request.headers.get("x-forwarded-proto")
    if not proto:
        # Modal serves only over HTTPS, even if its proxy does not say so.
        proto = "https" if host.endswith(".modal.run") else request.url.scheme
    return f"{proto}://{host}"


def create_app(
    settings: Settings | None = None,
    render_fn: RenderFn | None = None,
    recorder: SheetRecorder | None = None,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    if recorder is None and settings.sheet_webhook_url:
        recorder = SheetRecorder(settings.sheet_webhook_url, settings.sheet_token)
    if recorder is None:
        log.warning("SHEET_WEBHOOK_URL is not set: names, emails and renders are NOT being recorded")

    def on_result(job: Job, submitter: Submitter) -> None:
        if recorder is not None:
            recorder.add(record_row(job, submitter))

    manager = JobManager(settings, render_fn or make_renderer(settings), on_result=on_result)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if recorder is not None:
            recorder.start()
        manager.start()
        yield
        manager.stop()
        if recorder is not None:
            recorder.stop()

    app = FastAPI(title="Render the Molecule", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.manager = manager
    # The 3D viewer's script and structure files shrink to a quarter (PNGs are skipped).
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        if field and field not in SELF_EXPLAINING_FIELDS:
            message = f"{field}: {message}"
        return _error(422, message)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/privacy", include_in_schema=False)
    def privacy() -> FileResponse:
        return FileResponse(STATIC_DIR / "privacy.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", **manager.stats()}

    @app.get("/api/options")
    def options() -> dict:
        return option_lists()

    versions = about.versions()

    @app.get("/api/cite")
    def cite(pdb_id: str, request: Request):
        """How to credit and cite an image of this entry."""
        try:
            code = RenderRequest(pdb_id=pdb_id).pdb_id
        except ValidationError:
            return _error(422, "Not a valid PDB ID.")
        return {
            "credit": about.credit_line(code),
            "legend": about.legend_sentence(code, versions),
            "references": about.references(code, _base_url(request, settings), versions),
        }

    @app.get("/api/structure/{pdb_id}")
    def structure(pdb_id: str):
        """The entry's structure file (BinaryCIF), for the 3D preview.

        Served from this server's download cache, so the preview needs no other
        site, and the render that usually follows does not download it again.
        """
        try:
            code = RenderRequest(pdb_id=pdb_id).pdb_id
        except ValidationError:
            return _error(422, "Not a valid PDB ID.")
        try:
            path = fetch_structure(code, settings)
        except UserError as exc:
            return _error(404, str(exc))
        return FileResponse(path, media_type="application/octet-stream",
                            headers={"Cache-Control": "public, max-age=86400"})

    preview_limiter = RateLimiter(*PREVIEW_RECORDS_LIMIT)

    @app.post("/api/preview-saved", status_code=204)
    def preview_saved(body: Submission, request: Request):
        """Record a "Save preview image" in the Google Sheet (the image itself never leaves
        the visitor's browser). Same details and checks as a render."""
        if not preview_limiter.allow(_client_id(request)):
            return _error(429, "Many preview images in a short time; this one was not recorded.")
        if recorder is not None:
            submitter = Submitter(
                name=body.name, email=body.email, base_url=_base_url(request, settings),
                institution=body.institution, country=body.country,
            )
            recorder.add(preview_row(body.render_request(), submitter))
        return Response(status_code=204)

    @app.post("/api/render", status_code=202)
    def submit(body: Submission, request: Request):
        submitter = Submitter(
            name=body.name, email=body.email, base_url=_base_url(request, settings),
            institution=body.institution, country=body.country,
        )
        try:
            job = manager.submit(body.render_request(), _client_id(request), submitter)
        except QueueFull:
            return _error(503, "The render queue is full right now. Please try again in a few minutes.")
        except TooManyJobs:
            return _error(
                429,
                "You already have renders waiting. Please wait for them to finish first.",
            )
        return manager.snapshot(job)

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        job = manager.get(job_id)
        if job is None:
            return _error(404, "This job is unknown, possibly because the server restarted. Please submit it again.")
        return manager.snapshot(job)

    @app.get("/renders/{name}", include_in_schema=False)
    def render_file(name: str):
        if not RENDER_NAME_RE.fullmatch(name):
            return _error(404, "Not found")
        path = settings.renders_dir / name
        if not path.exists():
            return _error(404, "This image has expired from the cache. Please render it again.")
        # File names are content hashes, so the bytes never change.
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
