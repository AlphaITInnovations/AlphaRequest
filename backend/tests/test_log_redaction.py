"""Unit-Tests für die Log-Redaction (ohne I-O)."""

from backend.utils.log_redaction import redact_secrets, REDACTED


def test_redigiert_oauth_callback_code_und_state():
    line = 'GET /api/v1/auth/callback?code=ABC123.def&state=xyz789 HTTP/1.1'
    out = redact_secrets(line)
    assert 'ABC123.def' not in out
    assert 'xyz789' not in out
    assert f'code={REDACTED}' in out
    assert f'state={REDACTED}' in out


def test_redigiert_token_in_json():
    out = redact_secrets('{"access_token": "eyJhbGciOi...", "foo": "bar"}')
    assert 'eyJhbGciOi' not in out
    assert REDACTED in out
    assert '"foo": "bar"' in out   # unbeteiligte Felder bleiben


def test_redigiert_passwort_query():
    assert redact_secrets('login?password=hunter2') == f'login?password={REDACTED}'


def test_laesst_harmlose_zeilen_unveraendert():
    line = 'GET /api/v1/tickets?page=1&status=archived HTTP/1.1'
    assert redact_secrets(line) == line


def test_leere_und_nicht_strings():
    assert redact_secrets('') == ''
    assert redact_secrets(None) is None  # type: ignore[arg-type]
