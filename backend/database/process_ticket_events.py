"""
Verlauf (Historie) und Nachträge der Prozess-Tickets – append-only.

Warum eine eigene Tabelle statt eines JSON-Blobs am Ticket (so löst es das
Alt-System in `tickets.history`):
  * Der Verlauf wächst unbegrenzt. Als Blob müsste er bei JEDEM Eintrag komplett
    gelesen, geparst und neu geschrieben werden – und läge in jeder Ticket-Antwort
    mit drin, obwohl ihn nur die Detailansicht braucht.
  * Er ist so blätterbar (die Detailansicht lädt nur die letzten N Einträge).
  * Nachträge sind fachliche Aussagen von Menschen. Niemand soll sie nachträglich
    verändern können – deshalb gibt es hier bewusst KEIN UPDATE und KEIN DELETE.

`details_json` darf Feldschlüssel enthalten (z. B. „welche Felder wurden
geändert"). Die sind nicht für jeden sichtbar: die Redaktion beim Lesen macht
`backend/services/process_events.py`, nicht diese Schicht.

`epoch` spiegelt den Runtime-Epoch (§7) – nach einem Reopen laufen die Einträge
also erkennbar in einem neuen Durchlauf.
"""
import json
from typing import Optional

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone
from backend.utils.timeutil import to_db_datetime, utcnow

PROCESS_TICKET_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS process_ticket_events (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id    INT NOT NULL,
    epoch        INT NOT NULL DEFAULT 0,
    phase_key    VARCHAR(64) NULL,
    action       VARCHAR(64) NOT NULL,
    actor_id     VARCHAR(255) NULL,
    actor_name   VARCHAR(255) NULL,
    actor_type   VARCHAR(16) NOT NULL DEFAULT 'user',
    internal     TINYINT(1) NOT NULL DEFAULT 0,
    body         MEDIUMTEXT NULL,
    details_json MEDIUMTEXT NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pte_ticket (ticket_id, id),
    INDEX idx_pte_action (ticket_id, action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# Idempotente In-Place-Migrationen (für bereits bestehende Tabellen).
PROCESS_TICKET_EVENTS_MIGRATIONS = [
    "ALTER TABLE process_ticket_events ADD INDEX IF NOT EXISTS idx_pte_action (ticket_id, action)",
]

_COLS = ("id, ticket_id, epoch, phase_key, action, actor_id, actor_name, actor_type, "
         "internal, body, details_json, created_at")


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, PROCESS_TICKET_EVENTS_DDL)
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: dict) -> dict:
    out = dict(row)
    v = out.get("created_at")
    if hasattr(v, "isoformat"):
        # Die Spalte hält NAIVE UTC (s. add_event). Ohne Offset würde der Browser
        # sie als Lokalzeit lesen – der Verlauf wäre um den UTC-Versatz verschoben.
        out["created_at"] = (v.isoformat() if v.tzinfo is not None
                             else v.isoformat() + "+00:00")
    else:
        out["created_at"] = v
    out["internal"] = bool(out.get("internal"))
    try:
        out["details"] = json.loads(out["details_json"]) if out.get("details_json") else {}
    except (ValueError, TypeError):
        # Kaputtes JSON darf den Verlauf nicht unlesbar machen.
        out["details"] = {}
    out.pop("details_json", None)
    return out


def add_event(*, ticket_id: int, action: str, actor_id: Optional[str],
              actor_name: Optional[str], actor_type: str = "user",
              phase_key: Optional[str] = None, epoch: int = 0,
              internal: bool = False, body: Optional[str] = None,
              details: Optional[dict] = None) -> dict:
    conn = get_connection()
    try:
        # `created_at` ausdrücklich als naive UTC – nicht per DEFAULT
        # CURRENT_TIMESTAMP: das hinge an der Zeitzone des DB-Servers, und der
        # Verlauf würde je nach Deployment verschoben aussehen.
        _exec(conn,
              "INSERT INTO process_ticket_events "
              "(ticket_id, epoch, phase_key, action, actor_id, actor_name, actor_type, "
              " internal, body, details_json, created_at) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
              (ticket_id, int(epoch), phase_key, action, actor_id, actor_name, actor_type,
               1 if internal else 0, body,
               json.dumps(details, ensure_ascii=False) if details else None,
               to_db_datetime(utcnow())))
        new_id = _fetchone(conn, "SELECT LAST_INSERT_ID() AS id")["id"]
        conn.commit()
        row = _fetchone(conn, f"SELECT {_COLS} FROM process_ticket_events WHERE id = %s",
                        (new_id,))
    finally:
        conn.close()
    return _row_to_dict(row) if row else {}


def list_for_ticket(ticket_id: int, *, limit: int = 100, offset: int = 0,
                    ) -> tuple[list[dict], int]:
    """Verlauf eines Tickets, ÄLTESTE zuerst (chronologisch lesbar).

    Blätterung wandert vom Anfang – bei sehr langen Verläufen liest die Oberfläche
    also weiter, statt zurück. Das passt zur Timeline-Darstellung.
    """
    conn = get_connection()
    try:
        rows = _fetchall(conn,
                         f"SELECT {_COLS} FROM process_ticket_events "
                         "WHERE ticket_id = %s ORDER BY id ASC LIMIT %s OFFSET %s",
                         (ticket_id, int(limit), int(offset)))
        cnt = _fetchone(conn, "SELECT COUNT(*) AS c FROM process_ticket_events "
                              "WHERE ticket_id = %s", (ticket_id,))
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows], int((cnt or {}).get("c") or 0)


def count_for_ticket(ticket_id: int) -> int:
    conn = get_connection()
    try:
        cnt = _fetchone(conn, "SELECT COUNT(*) AS c FROM process_ticket_events "
                              "WHERE ticket_id = %s", (ticket_id,))
    finally:
        conn.close()
    return int((cnt or {}).get("c") or 0)
