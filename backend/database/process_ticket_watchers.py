"""
Beobachter (Watcher) eines Prozess-Tickets.

Beobachten heißt: mitlesen dürfen, ohne zuständig zu sein (`process_access.may_view`
nimmt die IDs entgegen) und über Phasenwechsel/Nachträge benachrichtigt werden.

Eigene Tabelle, NICHT die Alt-Tabelle `ticket_watchers` um `entity_type` erweitert
(wie bei den Anhängen): dort ist `PRIMARY KEY (ticket_id, user_id)`, und ein
Primärschlüssel-Tausch (DROP/ADD PRIMARY KEY) lässt sich in der Startup-Migration
nicht idempotent formulieren – beim zweiten Start würde er scheitern. Ohne
`entity_type` IM Schlüssel würden sich Alt-Ticket #7 und Prozess-Ticket #7
gegenseitig überschreiben.
"""
from typing import Iterable, Optional

from backend.database.connection import get_connection, _exec, _fetchall

PROCESS_TICKET_WATCHERS_DDL = """
CREATE TABLE IF NOT EXISTS process_ticket_watchers (
    ticket_id  INT NOT NULL,
    user_id    VARCHAR(255) NOT NULL,
    user_name  VARCHAR(255) NULL,
    added_by   VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticket_id, user_id),
    INDEX idx_ptw_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, PROCESS_TICKET_WATCHERS_DDL)
        conn.commit()
    finally:
        conn.close()


# ── Lesen ─────────────────────────────────────────────────────────────────────

def list_watchers(ticket_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = _fetchall(conn,
                         "SELECT user_id, user_name, added_by, created_at "
                         "FROM process_ticket_watchers WHERE ticket_id = %s "
                         "ORDER BY created_at ASC, user_id ASC",
                         (ticket_id,))
    finally:
        conn.close()
    return [{"id": r["user_id"], "name": r.get("user_name"),
             "added_by": r.get("added_by"),
             "created_at": (r["created_at"].isoformat()
                            if hasattr(r.get("created_at"), "isoformat")
                            else r.get("created_at"))}
            for r in rows]


def watcher_ids(ticket_id: int) -> set[str]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT user_id FROM process_ticket_watchers "
                               "WHERE ticket_id = %s", (ticket_id,))
    finally:
        conn.close()
    return {r["user_id"] for r in rows}


def watcher_ids_for_tickets(ticket_ids: Iterable[int]) -> dict[int, set[str]]:
    """Beobachter mehrerer Tickets in EINER Abfrage (Listen-Endpunkt: kein N+1)."""
    ids = [int(t) for t in ticket_ids]
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    conn = get_connection()
    try:
        rows = _fetchall(conn,
                         "SELECT ticket_id, user_id FROM process_ticket_watchers "
                         f"WHERE ticket_id IN ({placeholders})", tuple(ids))
    finally:
        conn.close()
    out: dict[int, set[str]] = {}
    for r in rows:
        out.setdefault(int(r["ticket_id"]), set()).add(r["user_id"])
    return out


def ticket_ids_for_watcher(user_id: str) -> list[int]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT ticket_id FROM process_ticket_watchers "
                               "WHERE user_id = %s", (user_id,))
    finally:
        conn.close()
    return [int(r["ticket_id"]) for r in rows]


# ── Schreiben ─────────────────────────────────────────────────────────────────

def add_watcher(ticket_id: int, user_id: str, user_name: Optional[str] = None,
                added_by: Optional[str] = None) -> bool:
    """True, wenn neu eingetragen; False, wenn schon Beobachter (idempotent)."""
    if not user_id:
        return False
    existing = watcher_ids(ticket_id)
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO process_ticket_watchers (ticket_id, user_id, user_name, added_by) "
              "VALUES (%s, %s, %s, %s) "
              "ON DUPLICATE KEY UPDATE user_name = VALUES(user_name)",
              (ticket_id, user_id, user_name, added_by))
        conn.commit()
    finally:
        conn.close()
    return user_id not in existing


def remove_watcher(ticket_id: int, user_id: str) -> bool:
    """True, wenn tatsächlich einer entfernt wurde."""
    existing = watcher_ids(ticket_id)
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM process_ticket_watchers "
                    "WHERE ticket_id = %s AND user_id = %s", (ticket_id, user_id))
        conn.commit()
    finally:
        conn.close()
    return user_id in existing
