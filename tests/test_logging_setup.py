import io, json, logging


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
