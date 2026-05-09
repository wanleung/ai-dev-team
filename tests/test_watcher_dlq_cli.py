"""Tests for the --list-dlq CLI command."""
import json


def test_list_dlq_prints_entries(capsys, tmp_path):
    """--list-dlq prints a table of DLQ entries to stdout."""
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    entry = {
        "id": "entry-001",
        "issue_number": 42,
        "tracker_repo": "owner/repo",
        "label": "ai-dev",
        "model": "gpt-4o",
        "num_engineers": 2,
        "failed_at": "2026-01-01T12:00:00Z",
        "error": {"message": "LLM timeout"},
        "target_repo": "",
        "attempt_count": 1,
    }
    (dlq_dir / "entry-001.json").write_text(json.dumps(entry))

    fake_config = {
        "reliability": {
            "dead_letter": {
                "enabled": True,
                "backend": "file",
                "file": {"path": str(dlq_dir)},
            }
        }
    }

    from watcher import _cmd_list_dlq
    _cmd_list_dlq(fake_config)

    captured = capsys.readouterr()
    assert "entry-001" in captured.out
    assert "42" in captured.out
    assert "LLM timeout" in captured.out


def test_list_dlq_shows_empty_message_when_no_entries(capsys, tmp_path):
    """--list-dlq prints a 'no entries' message when DLQ is empty."""
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()

    fake_config = {
        "reliability": {
            "dead_letter": {
                "enabled": True,
                "backend": "file",
                "file": {"path": str(dlq_dir)},
            }
        }
    }

    from watcher import _cmd_list_dlq
    _cmd_list_dlq(fake_config)

    captured = capsys.readouterr()
    assert "empty" in captured.out.lower() or "no entries" in captured.out.lower()
