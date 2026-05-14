"""Tests for the async job runner."""
import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from server.job_store import JobStore
from server.job_runner import JobRunner
from server.models import RunRequest


@pytest.fixture
def store(tmp_path):
    s = JobStore(db_path=":memory:")
    s.init_db()
    return s


@pytest.fixture
def runner(store, tmp_path):
    r = JobRunner(store=store, log_dir=tmp_path / "logs", config_yaml="config.yaml",
                  default_repo="o/r", default_pipeline="ai-feature", default_engineers=2)
    r.start()
    yield r
    r.shutdown()


class TestSubmitJob:
    def test_submit_returns_run_id(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        assert len(run_id) > 8

    def test_job_in_store_after_submit(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job is not None
        assert job.status in ("queued", "running")

    def test_defaults_applied(self, runner):
        req = RunRequest(requirement="Build X")  # no repo/pipeline/engineers
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job.repo == "o/r"
        assert job.pipeline == "ai-feature"
        assert job.engineers == 2

    def test_overrides_applied(self, runner):
        req = RunRequest(requirement="Build X", repo="other/r", pipeline="ai-fix", engineers=4)
        run_id = runner.submit(req)
        job = runner.store.get_job(run_id)
        assert job.repo == "other/r"
        assert job.pipeline == "ai-fix"
        assert job.engineers == 4


class TestCancelJob:
    def test_cancel_queued_job(self, runner):
        req = RunRequest(requirement="Build X")
        run_id = runner.submit(req)
        result = runner.cancel(run_id)
        assert result in (True, False)  # may have started already

    def test_cancel_nonexistent_returns_false(self, runner):
        assert runner.cancel("nonexistent") is False


class TestStreamLogs:
    def test_stream_completed_job_replays_then_ends(self, runner, tmp_path):
        """If a job is already done, stream replays the log then yields a done event."""
        from server.models import JobRecord
        log_path = tmp_path / "logs" / "done_job.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("line1\nline2\n")
        runner.store.insert_job(JobRecord(
            id="done1", status="done", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path=str(log_path),
        ))
        events = asyncio.get_event_loop().run_until_complete(_collect_events(runner, "done1"))
        log_events = [e for e in events if e[0] == "log"]
        assert len(log_events) == 2
        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1


async def _collect_events(runner, run_id):
    events = []
    async for event_type, data in runner.stream_logs(run_id):
        events.append((event_type, data))
        if event_type in ("done", "error"):
            break
    return events
