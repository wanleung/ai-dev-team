"""Tests for SQLite job store."""
import json
import pytest
from server.job_store import JobStore
from server.models import JobRecord


@pytest.fixture
def store():
    """In-memory SQLite job store for tests."""
    s = JobStore(db_path=":memory:")
    s.init_db()
    return s


class TestJobStoreInit:
    def test_init_creates_table(self, store):
        # Should not raise; table exists
        jobs = store.list_jobs(limit=10)
        assert jobs == []

    def test_interrupted_on_init(self, tmp_path):
        """Running jobs become 'interrupted' when store is re-initialised."""
        s = JobStore(db_path=str(tmp_path / "jobs.db"))
        s.init_db()
        s.insert_job(JobRecord(
            id="r1", status="running", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/r1.log",
        ))
        # Re-init simulates server restart
        s2 = JobStore(db_path=str(tmp_path / "jobs.db"))
        s2.init_db()
        job = s2.get_job("r1")
        assert job.status == "interrupted"


class TestInsertGet:
    def test_insert_and_get(self, store):
        job = JobRecord(
            id="abc", status="queued", requirement="Build X",
            repo="o/r", pipeline="ai-feature", engineers=2,
            created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
            log_path="/tmp/abc.log",
        )
        store.insert_job(job)
        fetched = store.get_job("abc")
        assert fetched.id == "abc"
        assert fetched.status == "queued"

    def test_get_missing_returns_none(self, store):
        assert store.get_job("nonexistent") is None


class TestUpdateStatus:
    def test_update_status(self, store):
        job = JobRecord(
            id="j1", status="queued", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/j1.log",
        )
        store.insert_job(job)
        store.update_status("j1", "running")
        assert store.get_job("j1").status == "running"

    def test_set_result(self, store):
        job = JobRecord(
            id="j2", status="running", requirement="x", repo="o/r",
            pipeline="p", engineers=1, created_at="t", updated_at="t",
            log_path="/tmp/j2.log",
        )
        store.insert_job(job)
        store.set_result("j2", "done", '{"verdict":"approved"}')
        fetched = store.get_job("j2")
        assert fetched.status == "done"
        assert json.loads(fetched.result_json)["verdict"] == "approved"

    def test_update_status_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.update_status("nonexistent", "running")

    def test_set_result_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.set_result("nonexistent", "done", "{}")


class TestListJobs:
    def test_list_ordered_by_created_desc(self, store):
        for i, ts in enumerate(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"]):
            store.insert_job(JobRecord(
                id=f"j{i}", status="done", requirement="x", repo="o/r",
                pipeline="p", engineers=1, created_at=ts, updated_at=ts,
                log_path=f"/tmp/j{i}.log",
            ))
        jobs = store.list_jobs(limit=10)
        assert jobs[0].id == "j1"   # most recent first

    def test_list_respects_limit(self, store):
        for i in range(5):
            store.insert_job(JobRecord(
                id=f"j{i}", status="done", requirement="x", repo="o/r",
                pipeline="p", engineers=1,
                created_at=f"2026-01-0{i+1}T00:00:00Z",
                updated_at=f"2026-01-0{i+1}T00:00:00Z",
                log_path=f"/tmp/j{i}.log",
            ))
        assert len(store.list_jobs(limit=3)) == 3
