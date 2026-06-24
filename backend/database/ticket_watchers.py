"""
Beobachter (Watcher) eines Tickets – beliebig viele Nutzer können ein Ticket
beobachten und sehen es im Dashboard unter „Beobachter". Der Ersteller wird beim
Anlegen automatisch als Beobachter eingetragen.

Tabelle: ticket_watchers
  - ticket_id  INT           (FK auf tickets.id, ohne harte Constraint)
  - user_id    VARCHAR(255)  (Microsoft Object ID)
  - user_name  VARCHAR(255)  (Anzeigename, denormalisiert für die Liste)
  - PRIMARY KEY (ticket_id, user_id)
"""

from backend.database.connection import get_connection, _exec, _fetchall


# ── DDL ───────────────────────────────────────────────────────────────────────

TICKET_WATCHERS_DDL = """
CREATE TABLE IF NOT EXISTS ticket_watchers (
    ticket_id  INT           NOT NULL,
    user_id    VARCHAR(255)  NOT NULL,
    user_name  VARCHAR(255)  NULL,
    PRIMARY KEY (ticket_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, TICKET_WATCHERS_DDL)
        conn.commit()
    finally:
        conn.close()


# ── Read ──────────────────────────────────────────────────────────────────────

def list_watchers(ticket_id: int) -> list[dict]:
    """Beobachter eines Tickets: [{id, name}, ...]"""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT user_id, user_name FROM ticket_watchers WHERE ticket_id = %s",
            (ticket_id,),
        )
    finally:
        conn.close()
    return [{"id": r["user_id"], "name": r["user_name"]} for r in rows]


def list_ticket_ids_for_watcher(user_id: str) -> list[int]:
    """Alle Ticket-IDs, die der Nutzer beobachtet."""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT ticket_id FROM ticket_watchers WHERE user_id = %s",
            (user_id,),
        )
    finally:
        conn.close()
    return [int(r["ticket_id"]) for r in rows]


def is_watcher(ticket_id: int, user_id: str) -> bool:
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT 1 FROM ticket_watchers WHERE ticket_id = %s AND user_id = %s LIMIT 1",
            (ticket_id, user_id),
        )
    finally:
        conn.close()
    return len(rows) > 0


# ── Write ─────────────────────────────────────────────────────────────────────

def add_watcher(ticket_id: int, user_id: str, user_name: str | None = None) -> None:
    if not user_id:
        return
    conn = get_connection()
    try:
        _exec(
            conn,
            "INSERT INTO ticket_watchers (ticket_id, user_id, user_name) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE user_name = VALUES(user_name)",
            (ticket_id, user_id, user_name),
        )
        conn.commit()
    finally:
        conn.close()


def remove_watcher(ticket_id: int, user_id: str) -> None:
    conn = get_connection()
    try:
        _exec(
            conn,
            "DELETE FROM ticket_watchers WHERE ticket_id = %s AND user_id = %s",
            (ticket_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def backfill_owner_watchers() -> None:
    """
    Trägt für bestehende Tickets den Ersteller als Beobachter nach (idempotent).
    Wird einmalig beim Start aufgerufen.
    """
    conn = get_connection()
    try:
        _exec(
            conn,
            "INSERT IGNORE INTO ticket_watchers (ticket_id, user_id, user_name) "
            "SELECT id, owner_id, owner_name FROM tickets "
            "WHERE owner_id IS NOT NULL AND owner_id <> ''",
        )
        conn.commit()
    finally:
        conn.close()
