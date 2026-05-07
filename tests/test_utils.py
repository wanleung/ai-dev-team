from utils import sanitise


def test_sanitise_replaces_single_secret():
    assert sanitise("error: https://mytoken@host/repo", "mytoken") == "error: https://***@host/repo"


def test_sanitise_replaces_multiple_secrets():
    result = sanitise("tok1 and tok2 here", "tok1", "tok2")
    assert result == "*** and *** here"


def test_sanitise_empty_secret_is_safe():
    assert sanitise("no change", "", None) == "no change"


def test_sanitise_no_match_returns_unchanged():
    assert sanitise("hello world", "secret") == "hello world"


def test_sanitise_multiple_occurrences():
    assert sanitise("x secret x secret x", "secret") == "x *** x *** x"
