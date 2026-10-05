"""/start-auth darf nur eine WIRKLICH gültige Session kurzschließen.

Regression: eine tote Session (Server-Neustart → boot_id passt nicht, oder Admin-
Force-Logout → Server-Row weg) trug weiter `user` im Cookie. Früher bounced
/start-auth sie endlos zur Frontend-URL (die dann 401t); erst /logout brach den
Zwischenzustand. `_session_is_live` entscheidet das jetzt serverseitig."""
from backend.api.v1 import auth


def _sess(**kw):
    base = {"user": {"id": "x"}, "sid": "s1", "boot_id": auth.SERVER_BOOT_ID}
    base.update(kw)
    return base


def test_live_session_true(monkeypatch):
    monkeypatch.setattr(auth, "get_session", lambda sid: {"sid": sid})
    assert auth._session_is_live(_sess()) is True


def test_no_user_false(monkeypatch):
    monkeypatch.setattr(auth, "get_session", lambda sid: {"sid": sid})
    assert auth._session_is_live(_sess(user=None)) is False


def test_boot_id_mismatch_false(monkeypatch):
    """Server-Neustart: boot_id im Cookie ≠ aktueller SERVER_BOOT_ID."""
    monkeypatch.setattr(auth, "get_session", lambda sid: {"sid": sid})
    assert auth._session_is_live(_sess(boot_id="alt")) is False


def test_no_sid_false(monkeypatch):
    monkeypatch.setattr(auth, "get_session", lambda sid: {"sid": sid})
    assert auth._session_is_live(_sess(sid=None)) is False


def test_force_logout_row_missing_false(monkeypatch):
    """Admin-Force-Logout: Server-Row ist weg → tot, auch wenn der Cookie noch `user` trägt."""
    monkeypatch.setattr(auth, "get_session", lambda sid: None)
    assert auth._session_is_live(_sess()) is False


def test_db_error_fail_open_true(monkeypatch):
    def boom(sid):
        raise RuntimeError("db down")
    monkeypatch.setattr(auth, "get_session", boom)
    assert auth._session_is_live(_sess()) is True
