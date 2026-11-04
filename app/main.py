"""HTTP API and web page.

Run with:  uvicorn --factory app.main:create_app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .errors import QueueFull, TooManyJobs
from .jobs import JobManager
from .options import RenderRequest, option_lists
from .renderer import RenderFn, make_renderer

STATIC_DIR = Path(__file__).resolve().parent / "static"
RENDER_NAME_RE = re.compile(r"^[0-9a-f]{64}\.png$")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _client_id(request: Request) -> str:
    # Behind the Hugging Face / Cloudflare proxy the visitor's address is in
    # X-Forwarded-For. It can be spoofed, so it only drives the per-visitor
    # limit; the global queue limit is what actually protects the server.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, render_fn: RenderFn | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    manager = JobManager(settings, render_fn or make_renderer(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.start()
        yield
        manager.stop()

    app = FastAPI(title="Render the Molecule", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.manager = manager

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        if field and field != "pdb_id":
            message = f"{field}: {message}"
        return _error(422, message)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", **manager.stats()}

    @app.get("/api/options")
    def options() -> dict:
        return option_lists()

    @app.post("/api/render", status_code=202)
    def submit(body: RenderRequest, request: Request):
        try:
            job = manager.submit(body, _client_id(request))
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
