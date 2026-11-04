import time

import pytest

from app.errors import QueueFull, TooManyJobs, UserError
from app.jobs import GENERIC_ERROR, JobManager
from app.options import RenderRequest


def wait_for(manager, job, status, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if manager.snapshot(job)["status"] == status:
            return manager.snapshot(job)
        time.sleep(0.01)
    raise AssertionError(f"job stayed {manager.snapshot(job)['status']}, wanted {status}")


@pytest.fixture
def manager(settings, fake_renderer):
    m = JobManager(settings, fake_renderer)
    m.start()
    yield m
    fake_renderer.gate.set()
    m.stop()


def test_job_renders_and_second_request_hits_cache(manager, fake_renderer):
    req = RenderRequest(pdb_id="4hhb")
    job = manager.submit(req, "client-a")
    snap = wait_for(manager, job, "done")
    assert snap["image_url"] == f"/renders/{req.cache_key()}.png"
    assert manager.output_path(req.cache_key()).exists()

    again = manager.submit(RenderRequest(pdb_id="4HHB"), "client-b")
    assert again.status == "done" and again.cached
    assert len(fake_renderer.calls) == 1


def test_pruned_image_is_rendered_again_not_served_empty(manager, fake_renderer):
    req = RenderRequest(pdb_id="4hhb")
    wait_for(manager, manager.submit(req, "a"), "done")
    manager.output_path(req.cache_key()).unlink()  # as the cache pruner would

    again = manager.submit(req, "a")
    assert not again.cached
    wait_for(manager, again, "done")
    assert manager.output_path(req.cache_key()).stat().st_size > 0
    assert len(fake_renderer.calls) == 2


def test_identical_pending_requests_share_one_job(manager, fake_renderer):
    fake_renderer.gate.clear()
    first = manager.submit(RenderRequest(pdb_id="1ema"), "a")
    second = manager.submit(RenderRequest(pdb_id="1ema"), "b")
    assert first is second
    fake_renderer.gate.set()
    wait_for(manager, first, "done")
    assert len(fake_renderer.calls) == 1


def test_queue_position_and_limits(manager, fake_renderer, settings):
    fake_renderer.gate.clear()
    running = manager.submit(RenderRequest(pdb_id="1aaa"), "a")
    wait_for(manager, running, "running")
    queued = manager.submit(RenderRequest(pdb_id="1aab"), "a")
    assert manager.snapshot(queued)["jobs_ahead"] == 1

    with pytest.raises(TooManyJobs):  # max_active_per_client = 2
        manager.submit(RenderRequest(pdb_id="1aac"), "a")

    manager.submit(RenderRequest(pdb_id="1aad"), "b")
    manager.submit(RenderRequest(pdb_id="1aae"), "c")
    with pytest.raises(QueueFull):  # max_queue = 3
        manager.submit(RenderRequest(pdb_id="1aaf"), "d")
    fake_renderer.gate.set()


def test_user_error_message_is_shown(manager, fake_renderer):
    fake_renderer.fail_with = UserError("9zzz was not found")
    job = manager.submit(RenderRequest(pdb_id="9zzz"), "a")
    snap = wait_for(manager, job, "failed")
    assert snap["error"] == "9zzz was not found"
    assert snap["image_url"] is None


def test_crash_shows_generic_message_and_worker_survives(manager, fake_renderer):
    fake_renderer.fail_with = RuntimeError("segfault-ish")
    job = manager.submit(RenderRequest(pdb_id="2abc"), "a")
    assert wait_for(manager, job, "failed")["error"] == GENERIC_ERROR

    fake_renderer.fail_with = None
    retry = manager.submit(RenderRequest(pdb_id="2abc"), "a")  # failures are not cached
    wait_for(manager, retry, "done")
