import io, json, logging
import threading
import pytest


def test_configure_logging_no_crash():
    """configure_logging() runs without raising."""
    from logging_setup import configure_logging
    configure_logging(log_level="WARNING")   # use WARNING to avoid cluttering test output


def test_bind_run_id_appears_in_log_output(tmp_path):
    """After bind_run_id(), all log lines contain the run_id."""
    import structlog
    log_file = tmp_path / "test.log"
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="DEBUG", log_file=log_file)
    bind_run_id("abc12345")
    logger = logging.getLogger("test_logger")
    logger.info("hello from test")
    content = log_file.read_text()
    assert "abc12345" in content


def test_json_renderer_produces_valid_json(tmp_path):
    """Log file output is valid JSON lines."""
    log_file = tmp_path / "test.log"
    from logging_setup import configure_logging, bind_run_id
    configure_logging(log_level="DEBUG", log_file=log_file)
    bind_run_id("test999")
    logging.getLogger("json_test").warning("test message")
    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1
    parsed = json.loads(lines[-1])
    assert "event" in parsed or "message" in parsed


def test_file_logging_removes_handler_on_exit(tmp_path):
    """Handler is added inside context and removed on normal exit."""
    from logging_setup import file_logging
    log_file = tmp_path / "test.log"
    with file_logging(log_file) as fh:
        assert fh in logging.getLogger().handlers
        logging.getLogger().info("inside context")
    assert fh not in logging.getLogger().handlers
    assert log_file.exists()


def test_file_logging_removes_handler_on_exception(tmp_path):
    """Handler is removed even if an exception is raised inside the context."""
    from logging_setup import file_logging
    log_file = tmp_path / "test.log"
    with pytest.raises(RuntimeError):
        with file_logging(log_file) as fh:
            raise RuntimeError("boom")
    assert fh not in logging.getLogger().handlers


def test_file_logging_isolates_records_by_thread(tmp_path):
    """Records from different threads only appear in their own log file."""
    import time
    from logging_setup import file_logging, configure_logging

    # Ensure structlog is configured and root logger level allows INFO messages
    configure_logging(log_level="INFO")

    log1 = tmp_path / "run1.log"
    log2 = tmp_path / "run2.log"

    barrier = threading.Barrier(2)
    errors = []

    def thread1():
        try:
            with file_logging(log1):
                barrier.wait()                      # both threads now inside context
                logging.getLogger().info("thread1-message")
                barrier.wait()                      # wait for thread2 to log too
        except Exception as exc:
            errors.append(f"t1: {exc}")

    def thread2():
        try:
            with file_logging(log2):
                barrier.wait()
                logging.getLogger().info("thread2-message")
                barrier.wait()
        except Exception as exc:
            errors.append(f"t2: {exc}")

    t1 = threading.Thread(target=thread1)
    t2 = threading.Thread(target=thread2)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == [], f"Threads raised errors: {errors}"
    content1 = log1.read_text(encoding="utf-8")
    content2 = log2.read_text(encoding="utf-8")

    assert "thread1-message" in content1, "thread1 message missing from log1"
    assert "thread2-message" not in content1, "thread2 message leaked into log1"
    assert "thread2-message" in content2, "thread2 message missing from log2"
    assert "thread1-message" not in content2, "thread1 message leaked into log2"
