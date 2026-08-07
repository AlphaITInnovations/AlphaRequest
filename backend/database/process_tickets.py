"""
Persistenz der definitions-getriebenen Tickets (Prozess-Instanzen, Stufe 2).

Jedes Ticket PINNT (process_key, process_version) – die gepinnte Definition ist
maßgeblich für Felder/Phasen/Sichtbarkeit/Automations, egal welche Version später
veröffentlicht wird. `values_json` = flache Feldwerte (Key = Feld-Dot-Path);
`runtime_json` = Ablauf-Zustand (nie Feldwerte, §5.6).

Getrennte Tabelle vom Alt-System (`tickets`) → Parallelbetrieb während des Umbaus;
Cutover (Alt-System entfernen, ggf. Umbenennung) ist ein eigener späterer Schritt.
"""
import json
from typing import Optional

from backend.database.connection import get_connection, _exec, _fetchone, _fetchall
from backend.utils.timeutil import to_db_datetime


class ProcessTicketConflict(Exception):
    """Optimistic-Concurrency-Konflikt: das Ticket wurde zwischenzeitlich geändert."""


PROCESS_TICKETS_DDL = """
CREATE TABLE IF NOT EXISTS process_tickets (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    process_key       VARCHAR(150) NOT NULL,
    process_version   INT NOT NULL,
    title             VARCHAR(255) NOT NULL DEFAULT '',
    status            VARCHAR(30) NOT NULL DEFAULT 'in_progress',
    priority          VARCHAR(20) NOT NULL DEFAULT 'normal',
    owner_id          VARCHAR(255) NULL,
    owner_name        VARCHAR(255) NULL,
    values_json       LONGTEXT NOT NULL,
    runtime_json      LONGTEXT NOT NULL,
    rev               INT NOT NULL DEFAULT 0,
    next_timer_due_at DATETIME NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_process (process_key, process_version),
    INDEX idx_owner (owner_id),
    INDEX idx_next_timer (next_timer_due_at),
    INDEX idx_status_updated (status, updated_at),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# Idempotente In-Place-Migrationen (für bereits bestehende Tabellen).
PROCESS_TICKETS_MIGRATIONS = [
    "ALTER TABLE process_tickets ADD COLUMN IF NOT EXISTS rev INT NOT NULL DEFAULT 0",
    "ALTER TABLE process_tickets ADD INDEX IF NOT EXISTS idx_status_updated (status, updated_at)",
    "ALTER TABLE process_tickets ADD INDEX IF NOT EXISTS idx_updated (updated_at)",
    "ALTER TABLE process_tickets ADD INDEX IF NOT EXISTS idx_next_timer (next_timer_due_at)",
]

_COLS = ("id, process_key, process_version, title, status, priority, owner_id, owner_name, "
         "values_json, runtime_json, rev, next_timer_due_at, created_at, updated_at")


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, PROCESS_TICKETS_DDL)
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    for k in ("created_at", "updated_at", "next_timer_due_at"):
        v = out.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    try:
        out["values"] = json.loads(out["values_json"]) if out.get("values_json") else {}
    except Exception:
        out["values"] = {}
    try:
        out["runtime"] = json.loads(out["runtime_json"]) if out.get("runtime_json") else {}
    except Exception:
        out["runtime"] = {}
    return out


# ── Read ────────────────────────────────────────────────────────────────────

def get(ticket_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = _fetchone(conn, f"SELECT {_COLS} FROM process_tickets WHERE id=%s", (ticket_id,))
    finally:
        conn.close()
    return _row_to_dict(row)


def list_tickets(*, status: Optional[str] = None, process_key: Optional[str] = None,
                 owner_id: Optional[str] = None, q: Optional[str] = None,
                 limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    where = []
    params: list = []
    if status:
        where.append("status=%s"); params.append(status)
    if process_key:
        where.append("process_key=%s"); params.append(process_key)
    if owner_id:
        where.append("owner_id=%s"); params.append(owner_id)
    if q:
        where.append("title LIKE %s"); params.append(f"%{q}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    conn = get_connection()
    try:
        total_row = _fetchone(conn, f"SELECT COUNT(*) AS n FROM process_tickets{clause}", tuple(params))
        total = int(total_row["n"]) if total_row else 0
        rows = _fetchall(
            conn,
            f"SELECT {_COLS} FROM process_tickets{clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset),
        )
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows], total


# ── Write ───────────────────────────────────────────────────────────────────

def create(*, process_key: str, process_version: int, title: str, status: str,
           priority: str, owner_id: Optional[str], owner_name: Optional[str],
           values_json: str, runtime_json: str) -> dict:
    conn = get_connection()
    try:
        cur = _exec(
            conn,
            "INSERT INTO process_tickets (process_key, process_version, title, status, priority, "
            "owner_id, owner_name, values_json, runtime_json) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (process_key, process_version, title, status, priority, owner_id, owner_name,
             values_json, runtime_json),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return get(new_id)


def _run_guarded(conn, set_sql: str, params: list, ticket_id: int, expected_rev: Optional[int]):
    """Führt ein UPDATE mit rev-Bump aus; bei expected_rev zusätzlich
    WHERE rev=%s → rowcount 0 ⇒ Konflikt (zwischenzeitlich geändert)."""
    sql = f"UPDATE process_tickets SET {set_sql}, rev=rev+1 WHERE id=%s"
    params = list(params) + [ticket_id]
    if expected_rev is not None:
        sql += " AND rev=%s"
        params.append(expected_rev)
    cur = _exec(conn, sql, tuple(params))
    if expected_rev is not None and cur.rowcount == 0:
        conn.rollback()
        raise ProcessTicketConflict(f"Ticket #{ticket_id} wurde zwischenzeitlich geändert")


def update_values(ticket_id: int, values_json: str, title: Optional[str] = None,
                  expected_rev: Optional[int] = None) -> dict:
    conn = get_connection()
    try:
        if title is not None:
            _run_guarded(conn, "values_json=%s, title=%s", [values_json, title], ticket_id, expected_rev)
        else:
            _run_guarded(conn, "values_json=%s", [values_json], ticket_id, expected_rev)
        conn.commit()
    finally:
        conn.close()
    return get(ticket_id)


def update_runtime(ticket_id: int, *, runtime_json: str, status: str,
                   next_timer_due_at: Optional[str] = None,
                   expected_rev: Optional[int] = None) -> dict:
    conn = get_connection()
    try:
        _run_guarded(conn, "runtime_json=%s, status=%s, next_timer_due_at=%s",
                     [runtime_json, status, to_db_datetime(next_timer_due_at)],
                     ticket_id, expected_rev)
        conn.commit()
    finally:
        conn.close()
    return get(ticket_id)


# ── Scheduler-Support ─────────────────────────────────────────────────────────

_ACTIVE_CLAUSE = "status NOT IN ('archived', 'rejected')"


def list_due(now: str, limit: int = 200) -> list[dict]:
    """Aktive Tickets mit fälligem Timer (next_timer_due_at <= now).
    `now` wird wie jeder DATETIME-Wert normalisiert (naive UTC)."""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            f"SELECT {_COLS} FROM process_tickets WHERE next_timer_due_at IS NOT NULL "
            f"AND next_timer_due_at <= %s AND {_ACTIVE_CLAUSE} "
            "ORDER BY next_timer_due_at LIMIT %s",
            (to_db_datetime(now), limit),
        )
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def set_next_timer(ticket_id: int, next_timer_due_at: Optional[str],
                   expected_rev: Optional[int] = None) -> None:
    conn = get_connection()
    try:
        _run_guarded(conn, "next_timer_due_at=%s", [to_db_datetime(next_timer_due_at)],
                     ticket_id, expected_rev)
        conn.commit()
    finally:
        conn.close()


def set_priority(ticket_id: int, priority: str, expected_rev: Optional[int] = None) -> None:
    conn = get_connection()
    try:
        _run_guarded(conn, "priority=%s", [priority], ticket_id, expected_rev)
        conn.commit()
    finally:
        conn.close()


def set_status(ticket_id: int, status: str, expected_rev: Optional[int] = None) -> None:
    conn = get_connection()
    try:
        _run_guarded(conn, "status=%s", [status], ticket_id, expected_rev)
        conn.commit()
    finally:
        conn.close()
