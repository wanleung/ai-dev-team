"""Tests for server Pydantic models."""
import pytest
from server.models import RunRequest, RunSubmitted, JobRecord, RunDetail, RunSummary


class TestRunRequest:
    def test_defaults(self):
        r = RunRequest(requirement="Build a TODO app")
        assert r.requirement == "Build a TODO app"
        assert r.repo is None
        assert r.pipeline is None
        assert r.engineers is None

    def test_all_fields(self):
        r = RunRequest(requirement="x", repo="o/r", pipeline="ai-fix", engineers=3)
        assert r.repo == "o/r"
        assert r.engineers == 3


class TestJobRecord:
    def test_required_fields(self):
        j = JobRecord(
            id="abc",
            status="queued",
            requirement="Build X",
            repo="o/r",
            pipeline="ai-feature",
            engineers=2,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            log_path="/tmp/abc.log",
        )
        assert j.id == "abc"
        assert j.result_json is None

    def test_result_json_optional(self):
        j = JobRecord(
            id="x", status="done", requirement="r", repo="o/r",
            pipeline="p", engineers=1,
            created_at="t", updated_at="t", log_path="/tmp/x.log",
            result_json='{"verdict":"approved"}',
        )
        assert j.result_json == '{"verdict":"approved"}'


class TestRunSubmitted:
    def test_fields(self):
        s = RunSubmitted(run_id="abc", status="queued", stream_url="/runs/abc/stream")
        assert s.run_id == "abc"


class TestRunSummary:
    def test_fields(self):
        s = RunSummary(
            run_id="x", status="done", requirement="Build X",
            repo="o/r", pipeline="p",
            created_at="t", updated_at="t",
        )
        assert s.run_id == "x"
