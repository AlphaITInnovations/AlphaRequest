"""
In-App-Benachrichtigungen je Person (`user_notifications`).

Ergänzt die Mails – ersetzt sie NICHT: der Mailversand (services/process_actions)
bleibt unverändert und bewusst sparsam (Beobachter:innen bekommen z. B. keine
Mail). In der App darf es großzügiger sein; die Glocke zeigt, was an den eigenen
Aufträgen passiert ist.

Ein Eintrag ist ein fertig formulierter Text-Schnappschuss (Titel, Kurztext, Link)
– die Liste muss nichts nachladen oder neu berechnen. Er enthält bewusst KEINE
Feldwerte (Feld-Sichtbarkeit): nur Auftragstitel, Phase/Abteilung und Ereignis.

Zusammenfassen gegen Flut: Für Arten in `COALESCE_KINDS` gibt es je Person und
Auftrag höchstens EINEN ungelesenen Eintrag – ein neues Ereignis ERSETZT ihn
(alter ungelesener raus, neuer rein), statt einen weiteren anzulegen. So erzeugt
eine Kette automatischer Phasenwechsel nicht drei Meldungen hintereinander. Ersetzen
statt Aktualisieren hält die id-Reihenfolge = Zeitreihenfolge (Blättern per id).
"""
from typing import Iterable, Optional

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone
from backend.utils.logger import logger
from backend.utils.timeutil import to_db_datetime, utcnow

USER_NOTIFICATIONS_DDL = """
CREATE TABLE IF NOT EXISTS user_notifications (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(255) NOT NULL,
    ticket_id   INT          NULL,
    kind        VARCHAR(32)  NOT NULL,
    title       VARCHAR(255) NOT NULL,
    body        VARCHAR(500) NULL,
    link        VARCHAR(255) NULL,
    actor_name  VARCHAR(255) NULL,
    created_at  DATETIME     NOT NULL,
    read_at     DATETIME     NULL,
    INDEX idx_un_user (user_id, id),
    INDEX idx_un_unread (user_id, read_at),
    INDEX idx_un_coalesce (user_id, ticket_id, kind, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

#: Arten, die je (Person, Auftrag) zu EINEM ungelesenen Eintrag zusammengefasst werden.
COALESCE_KINDS = {"task", "progress"}

_COLS = "id, user_id, ticket_id, kind, title, body, link, actor_name, created_at, read_at"


def _iso(v) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        # Spalten halten naive UTC – mit Offset ausgeben, sonst läse der Browser Lokalzeit.
        return v.isoformat() if v.tzinfo is not None else v.isoformat() + "+00:00"
    return str(v)


def _row(r: dict) -> dict:
    out = dict(r)
    out["created_at"] = _iso(out.get("created_at"))
    out["read_at"] = _iso(out.get("read_at"))
    return out


def add_many(items: Iterable[dict]) -> int:
    """Einträge schreiben (je {user_id, ticket_id, kind, title, body, link,
    actor_name}). Zusammenfassbare Arten aktualisieren einen vorhandenen
    ungelesenen Eintrag. Gibt die Zahl betroffener Personen zurück."""
    items = [i for i in items if i.get("user_id")]
    if not items:
        return 0
    now = to_db_datetime(utcnow())
    conn = get_connection()
    try:
        for it in items:
            vals = (str(it["title"])[:255], (it.get("body") or None) and str(it["body"])[:500],
                    (it.get("link") or None) and str(it["link"])[:255],
                    (it.get("actor_name") or None) and str(it["actor_name"])[:255])
            if it["kind"] in COALESCE_KINDS and it.get("ticket_id") is not None:
                _exec(conn,
                      "DELETE FROM user_notifications "
                      "WHERE user_id=%s AND ticket_id=%s AND kind=%s AND read_at IS NULL",
                      (it["user_id"], it["ticket_id"], it["kind"]))
            _exec(conn,
                  "INSERT INTO user_notifications "
                  "(user_id, ticket_id, kind, title, body, link, actor_name, created_at) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                  (it["user_id"], it.get("ticket_id"), it["kind"], *vals, now))
        conn.commit()
    finally:
        conn.close()
    return len(items)


def list_for_user(user_id: str, *, limit: int = 20,
                  before_id: Optional[int] = None) -> list[dict]:
    """Neueste zuerst; `before_id` blättert ältere nach."""
    conn = get_connection()
    try:
        if before_id:
            rows = _fetchall(conn,
                             f"SELECT {_COLS} FROM user_notifications "
                             "WHERE user_id=%s AND id < %s ORDER BY id DESC LIMIT %s",
                             (user_id, int(before_id), int(limit)))
        else:
            rows = _fetchall(conn,
                             f"SELECT {_COLS} FROM user_notifications "
                             "WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                             (user_id, int(limit)))
    finally:
        conn.close()
    return [_row(r) for r in rows]


def unread_count(user_id: str) -> int:
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT COUNT(*) AS c FROM user_notifications "
                              "WHERE user_id=%s AND read_at IS NULL", (user_id,))
    finally:
        conn.close()
    return int((row or {}).get("c") or 0)


def mark_read(user_id: str, notification_id: int) -> None:
    """Nur EIGENE Einträge (user_id in der Bedingung – fremde ids greifen ins Leere)."""
    conn = get_connection()
    try:
        _exec(conn, "UPDATE user_notifications SET read_at=%s "
                    "WHERE id=%s AND user_id=%s AND read_at IS NULL",
              (to_db_datetime(utcnow()), int(notification_id), user_id))
        conn.commit()
    finally:
        conn.close()


def mark_all_read(user_id: str) -> None:
    conn = get_connection()
    try:
        _exec(conn, "UPDATE user_notifications SET read_at=%s "
                    "WHERE user_id=%s AND read_at IS NULL",
              (to_db_datetime(utcnow()), user_id))
        conn.commit()
    finally:
        conn.close()


def prune(read_older_than_days: int = 60, any_older_than_days: int = 180) -> None:
    """Aufräumen: Gelesenes nach 60 Tagen, alles nach 180 Tagen. Best-effort."""
    try:
        conn = get_connection()
        try:
            _exec(conn, "DELETE FROM user_notifications WHERE read_at IS NOT NULL "
                        "AND created_at < (UTC_TIMESTAMP() - INTERVAL %s DAY)",
                  (int(read_older_than_days),))
            _exec(conn, "DELETE FROM user_notifications "
                        "WHERE created_at < (UTC_TIMESTAMP() - INTERVAL %s DAY)",
                  (int(any_older_than_days),))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Benachrichtigungen aufräumen fehlgeschlagen")
