import logging
import os
import pytest
from unittest.mock import MagicMock, patch

import watcher
from utils import sanitise as _sanitise


def _exc_with_token(token: str) -> Exception:
    return Exception(f"https://x-access-token:{token}@github.com/owner/repo.git")


# ---------------------------------------------------------------------------
# Existing unit tests (simulate the sanitise call directly)
# ---------------------------------------------------------------------------

def test_dlq_enqueue_warning_sanitises_token(monkeypatch, caplog):
    """logger.warning for DLQ enqueue failure must not emit the raw token."""
    token = "ghp_SECRETTOKEN1234"
    monkeypatch.setenv("GITHUB_TOKEN", token)

    with caplog.at_level(logging.WARNING, logger="watcher"):
        logger = logging.getLogger("watcher")
        exc = _exc_with_token(token)
        logger.warning("Could not enqueue to DLQ: %s", _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")))

    assert token not in caplog.text
    assert "***" in caplog.text
    assert "Could not enqueue to DLQ" in caplog.text


def test_dlq_retry_warning_sanitises_token(monkeypatch, caplog):
    """logger.warning for DLQ retry failure must not emit the raw token."""
    token = "ghp_SECRETRETRY5678"
    monkeypatch.setenv("GITHUB_TOKEN", token)

    with caplog.at_level(logging.WARNING, logger="watcher"):
        logger = logging.getLogger("watcher")
        exc = _exc_with_token(token)
        logger.warning(
            "DLQ retry failed for issue #%d: %s",
            42,
            _sanitise(str(exc), os.environ.get("GITHUB_TOKEN", "")),
        )

    assert token not in caplog.text
    assert "***" in caplog.text
    assert "DLQ retry failed" in caplog.text


# ---------------------------------------------------------------------------
# Integration tests — exercise the real watcher code paths
# ---------------------------------------------------------------------------

def test_run_pipeline_dlq_enqueue_failure_sanitises_token(monkeypatch, caplog):
    """run_pipeline() DLQ-enqueue warning (line ~466) must not emit the raw token.

    Exercises the real code path: _dispatch raises → failure handling runs →
    dlq.enqueue() raises with an embedded token → logger.warning at line ~466.
    The token must be redacted in the captured log output.
    """
    token = "ghp_ENQUEUE_INTEGRATION_TOKEN"
    monkeypatch.setenv("GITHUB_TOKEN", token)

    mock_dlq = MagicMock()
    mock_dlq.enqueue.side_effect = Exception(
        f"https://x-access-token:{token}@github.com/owner/repo.git"
    )

    watcher_logger = logging.getLogger("watcher")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        with patch.object(watcher, "_dispatch", side_effect=RuntimeError("agent crashed")):
            with patch.object(watcher, "add_label"):
                with patch.object(watcher, "remove_label"):
                    with patch.object(watcher, "post_comment"):
                        watcher.run_pipeline(
                            issue_number=1,
                            tracker_repo="owner/repo",
                            label="ai-dev",
                            model="gpt-4",
                            logger=watcher_logger,
                            dlq=mock_dlq,
                        )

    assert token not in caplog.text, "Raw token must not appear in log output"
    assert "***" in caplog.text, "Redacted placeholder must appear in log output"
    assert "Could not enqueue to DLQ" in caplog.text, "Expected warning message missing"


def test_main_retry_dlq_failure_sanitises_token(monkeypatch, caplog, tmp_path):
    """main() --retry-dlq warning (line ~1539) must not emit the raw token.

    Exercises the real code path: main() --retry-dlq → dlq.drain() yields an
    entry → run_pipeline() raises with an embedded token → logger.warning at
    line ~1539.  The token must be redacted in the captured log output.
    """
    token = "ghp_RETRY_INTEGRATION_TOKEN"
    monkeypatch.setenv("GITHUB_TOKEN", token)

    # Minimal real config file so load_watcher_config() succeeds
    config_file = tmp_path / "watcher.yaml"
    config_file.write_text("settings: {}\nwatchers: []\n")

    # Mock DLQ entry
    entry = MagicMock()
    entry.issue_number = 99
    entry.tracker_repo = "owner/repo"
    entry.target_repo = "owner/repo"
    entry.label = "ai-dev"
    entry.model = "gpt-4"
    entry.num_engineers = 1

    mock_dlq = MagicMock()
    mock_dlq.drain.return_value = [entry]

    watcher_logger = logging.getLogger("watcher")

    with caplog.at_level(logging.WARNING, logger="watcher"):
        with patch("sys.argv", ["watcher", "--config", str(config_file), "--retry-dlq"]):
            with patch.object(watcher, "_setup_logging", return_value=watcher_logger):
                with patch.object(watcher, "_load_pipeline_config", return_value={}):
                    with patch("core.dead_letter.build_dlq", return_value=mock_dlq):
                        with patch.object(
                            watcher,
                            "run_pipeline",
                            side_effect=Exception(
                                f"https://x-access-token:{token}@github.com/owner/repo.git"
                            ),
                        ):
                            with pytest.raises(SystemExit):
                                watcher.main()

    assert token not in caplog.text, "Raw token must not appear in log output"
    assert "***" in caplog.text, "Redacted placeholder must appear in log output"
    assert "DLQ retry failed" in caplog.text, "Expected warning message missing"
