"""
Serverseitige Liste aktiver Sessions (`active_sessions`).

Ergänzt das signierte Session-Cookie um einen serverseitigen Zustand, damit der
Admin sehen kann, wer gerade eingeloggt ist, und einzelne Sessions/Nutzer gezielt
abmelden kann (Force-Logout).

Zwei Zeitstempel mit unterschiedlicher Aufgabe:
  - `last_activity` (im Cookie, NICHT hier) steuert das Inaktivitäts-Timeout.
  - `last_seen` (hier) steuert die Online-Anzeige; wird auch vom Heartbeat
    aktualisiert ("offener Tab = online"), verlängert das Timeout aber nicht.

Reliability: Bis auf `get_session` (das für den pro-Request-Validitätscheck bei
DB-Fehlern werfen MUSS, damit der Aufrufer fail-open reagieren kann) schlucken
alle Funktionen Fehler und loggen sie nur – die Session-Buchführung darf die
Fachlogik nie blockieren.
"""

from typing import Optional

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone
from backend.utils.config import config
from backend.utils.logger import logger


ACTIVE_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS active_sessions (
    sid         VARCHAR(64)  NOT NULL,
    user_id     VARCHAR(255) NOT NULL,
    user_name   VARCHAR(255) NULL,
    ip          VARCHAR(64)  NULL,
    user_agent  VARCHAR(512) NULL,
    created_at  DATETIME     NOT NULL,
    last_seen   DATETIME     NOT NULL,
    PRIMARY KEY (sid),
    INDEX idx_sessions_user (user_id),
    INDEX idx_sessions_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, ACTIVE_SESSIONS_DDL)
        conn.commit()
    finally:
        conn.close()


def upsert_session(sid: str, user_id: str, user_name: Optional[str],
                   ip: Optional[str], user_agent: Optional[str]) -> None:
    """Beim Login anlegen bzw. aktualisieren. Best-effort."""
    if not sid or not user_id:
        return
    try:
        conn = get_connection()
        try:
            _exec(
                conn,
                "INSERT INTO active_sessions "
                "(sid, user_id, user_name, ip, user_agent, created_at, last_seen) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), NOW()) "
                "ON DUPLICATE KEY UPDATE "
                "user_id=VALUES(user_id), user_name=VALUES(user_name), "
                "ip=VALUES(ip), user_agent=VALUES(user_agent), last_seen=NOW()",
                (sid, user_id, user_name, ip, (user_agent or "")[:512] or None),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("upsert_session fehlgeschlagen (sid=%s)", sid)


def get_session(sid: str) -> Optional[dict]:
    """Existenz + Alter der Session für den pro-Request-Check.

    Gibt {'sid', 'user_id', 'user_name', 'age_seconds'} zurück oder None (Session
    existiert nicht / wurde force-abgemeldet). WIRFT bei DB-Fehler bewusst weiter,
    damit `get_current_user` fail-open reagieren kann (kein Logout bei DB-Schluckauf).
    """
    if not sid:
        return None
    conn = get_connection()
    try:
        return _fetchone(
            conn,
            "SELECT sid, user_id, user_name, TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS age_seconds "
            "FROM active_sessions WHERE sid = %s",
            (sid,),
        )
    finally:
        conn.close()


def touch_session(sid: str, ip: Optional[str] = None) -> None:
    """`last_seen` auffrischen (Präsenz). Aufrufer drosselt via age_seconds;
    hier ohne Bedingung, best-effort."""
    if not sid:
        return
    try:
        conn = get_connection()
        try:
            _exec(
                conn,
                "UPDATE active_sessions SET last_seen = NOW(), ip = COALESCE(%s, ip) "
                "WHERE sid = %s",
                (ip, sid),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("touch_session fehlgeschlagen (sid=%s)", sid)


def delete_session(sid: str) -> None:
    """Einzelne Session entfernen (Logout / Force-Logout). Best-effort."""
    if not sid:
        return
    try:
        conn = get_connection()
        try:
            _exec(conn, "DELETE FROM active_sessions WHERE sid = %s", (sid,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("delete_session fehlgeschlagen (sid=%s)", sid)


def delete_sessions_for_user(user_id: str) -> list[str]:
    """Alle Sessions einer Person entfernen. Gibt die betroffenen sids zurück,
    damit der Aufrufer auch den In-Memory-Token-Store (TOKENS) purgen kann."""
    if not user_id:
        return []
    try:
        conn = get_connection()
        try:
            rows = _fetchall(
                conn, "SELECT sid FROM active_sessions WHERE user_id = %s", (user_id,)
            )
            sids = [r["sid"] for r in rows]
            if sids:
                _exec(conn, "DELETE FROM active_sessions WHERE user_id = %s", (user_id,))
                conn.commit()
            return sids
        finally:
            conn.close()
    except Exception:
        logger.exception("delete_sessions_for_user fehlgeschlagen (user=%s)", user_id)
        return []


def list_active_sessions(active_within_seconds: Optional[int] = None) -> list[dict]:
    """Aktive Sessions (neueste `last_seen` zuerst). Prunet vorher stale Rows.

    `age_seconds` (serverseitig berechnet, keine Client-Uhr) erlaubt der UI eine
    verlässliche Online-Anzeige."""
    window = int(active_within_seconds if active_within_seconds is not None
                 else config.SESSION_TIMEOUT)
    prune_stale(window)
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT sid, user_id, user_name, ip, user_agent, created_at, last_seen, "
            "TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS age_seconds "
            "FROM active_sessions "
            "WHERE last_seen >= (NOW() - INTERVAL %s SECOND) "
            "ORDER BY last_seen DESC",
            (window,),
        )
    finally:
        conn.close()

    result: list[dict] = []
    for r in rows:
        d = dict(r)
        for key in ("created_at", "last_seen"):
            v = d.get(key)
            d[key] = v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else "")
        d["age_seconds"] = int(d.get("age_seconds") or 0)
        result.append(d)
    return result


def clear_all_sessions() -> None:
    """Beim Server-Start: Tabelle leeren. Der Neustart hat via SERVER_BOOT_ID
    ohnehin alle Cookies invalidiert, also gibt es keine gültigen Sessions mehr."""
    try:
        conn = get_connection()
        try:
            _exec(conn, "DELETE FROM active_sessions")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("clear_all_sessions fehlgeschlagen")


def prune_stale(older_than_seconds: int) -> None:
    """Sessions entfernen, die länger als `older_than_seconds` nichts mehr
    gemeldet haben (abgelaufen). Best-effort."""
    try:
        conn = get_connection()
        try:
            _exec(
                conn,
                "DELETE FROM active_sessions WHERE last_seen < (NOW() - INTERVAL %s SECOND)",
                (int(older_than_seconds),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("prune_stale fehlgeschlagen")
