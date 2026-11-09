"""Record who rendered what in a Google Sheet.

Each finished request becomes one row, sent to a small Google Apps Script web
app (google-sheet/Code.gs) that appends it to a private Sheet. Rows are sent
by a background thread in batches and retried if the Sheet cannot be reached,
so recording never slows down or breaks rendering.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

import requests

from .jobs import Job, Submitter

log = logging.getLogger(__name__)

# Column order; must match KEYS in google-sheet/Code.gs.
ROW_KEYS = [
    "time", "name", "email", "pdb_id", "style", "color", "material", "viewpoint",
    "resolution", "quality", "background", "ligands", "assembly", "credit",
    "status", "cached", "render_s", "error", "link",
    # Added later, so they are the last columns and older rows stay aligned.
    "source", "institution", "country",
]


def record_row(job: Job, submitter: Submitter) -> dict:
    req = job.request
    render_s = ""
    if not job.cached and job.started_at and job.finished_at:
        render_s = round(job.finished_at - job.started_at, 1)
    row = {
        "time": int(submitter.submitted_at * 1000),  # Unix ms; the script makes it a date
        "name": submitter.name,
        "email": submitter.email,
        "pdb_id": req.pdb_id.upper(),
        "style": req.style,
        "color": req.color,
        "material": req.material,
        "viewpoint": "3D preview" if req.camera else req.viewpoint,  # the link holds the exact view
        "resolution": req.resolution,
        "quality": req.quality,
        "background": req.background,
        "ligands": "yes" if req.ligands else "no",
        "assembly": "yes" if req.assembly else "no",
        "credit": "yes" if req.credit else "no",
        "status": job.status,
        "cached": "yes" if job.cached else "no",
        "render_s": render_s,
        "error": job.error or "",
        "link": f"{submitter.base_url}/?{req.share_query()}",
        "source": "Web app",
        "institution": submitter.institution,
        "country": submitter.country,
    }
    return row


class SheetRecorder:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30,
        batch_size: int = 100,
        max_pending: int = 5000,
        retry_after: float = 5,
        max_retry_after: float = 300,
    ):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.batch_size = batch_size
        self.max_pending = max_pending
        self.retry_after = retry_after
        self.max_retry_after = max_retry_after
        self._pending: deque[dict] = deque()
        self._cv = threading.Condition()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def add(self, row: dict) -> None:
        with self._cv:
            if len(self._pending) >= self.max_pending:
                self._pending.popleft()
                log.warning("Google Sheet unreachable for a long time; dropped the oldest record")
            self._pending.append(row)
            self._cv.notify()

    def pending(self) -> int:
        with self._cv:
            return len(self._pending)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sheet-recorder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        with self._cv:
            self._stopping = True
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        delay = self.retry_after
        while True:
            with self._cv:
                while not self._pending and not self._stopping:
                    self._cv.wait()
                if not self._pending:  # stopping with nothing left to send
                    return
                batch = [self._pending.popleft() for _ in range(min(self.batch_size, len(self._pending)))]

            try:
                self._send(batch)
                delay = self.retry_after
                continue
            except Exception as exc:  # network error, bad token, Sheet quota...
                log.warning("could not record %d row(s) in the Google Sheet: %s", len(batch), exc)
                with self._cv:
                    self._pending.extendleft(reversed(batch))  # keep the original order
                    if self._stopping:
                        return  # do not hold up shutdown retrying
                    self._cv.wait(delay)
                delay = min(delay * 2, self.max_retry_after)

    def _send(self, rows: list[dict]) -> None:
        # Apps Script answers with a redirect to the result; requests follows it.
        resp = requests.post(
            self.url, json={"token": self.token, "rows": rows}, timeout=self.timeout
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(
                "the Sheet web app did not return JSON; check that it is deployed "
                "with access 'Anyone' and that SHEET_WEBHOOK_URL ends in /exec"
            ) from None
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "the Sheet web app reported an error")
        log.info("recorded %d row(s) in the Google Sheet", len(rows))
