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


# ── Listen/Kennzahlen für Dashboard & Metriken ────────────────────────────────
#
# Eigene, schmale Projektion: die JSON-Blobs müssen nicht durch jede Liste.
# `values_json` trägt die Feldwerte (LONGTEXT, und jede Ausgabe müsste erst durch
# den Sichtbarkeitsfilter §5.1) – in Übersichten wird davon nichts gebraucht.
_LIST_COLS = ("id, process_key, process_version, title, status, priority, "
              "owner_id, owner_name, rev, next_timer_due_at, created_at, updated_at")

# Zusätzlich `runtime_json`: der Ablaufzustand (Phase/Abteilungen, laut §5.6 NIE
# Feldwerte) ist nötig, um Zuständigkeit und aktuelle Phase zu bestimmen –
# `values_json` bleibt auch hier draußen.
_LIST_COLS_RUNTIME = _LIST_COLS + ", runtime_json"


def _row_to_list_dict(row: dict) -> dict:
    """Listen-Zeile aufbereiten: Datumsfelder als ISO, `runtime` geparst falls
    mitgelesen. Setzt bewusst KEIN `values` – die Feldwerte sind nicht geladen,
    und ein leeres Dict würde „keine Werte" statt „nicht geladen" suggerieren."""
    out = dict(row)
    for k in ("created_at", "updated_at", "next_timer_due_at"):
        v = out.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    if "runtime_json" in out:
        try:
            out["runtime"] = json.loads(out["runtime_json"]) if out["runtime_json"] else {}
        except Exception:
            out["runtime"] = {}
    return out


def list_for_owner(owner_id: str, limit: int = 25, *, active_only: bool = True,
                   include_runtime: bool = False) -> list[dict]:
    """Aufträge, die diese Person angelegt hat (owner_id) – neueste zuerst."""
    if not owner_id:
        return []
    cols = _LIST_COLS_RUNTIME if include_runtime else _LIST_COLS
    clause = f" AND {_ACTIVE_CLAUSE}" if active_only else ""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            f"SELECT {cols} FROM process_tickets WHERE owner_id=%s{clause} "
            "ORDER BY updated_at DESC LIMIT %s",
            (owner_id, limit),
        )
    finally:
        conn.close()
    return [_row_to_list_dict(r) for r in rows]


def list_active(limit: int = 200, *, include_runtime: bool = True) -> list[dict]:
    """Nicht-terminale Aufträge (weder archiviert noch abgelehnt), neueste zuerst.

    Bewusst mit `limit`: die Zugriffsprüfung (may_view) läuft je Zeile in Python,
    deshalb wird der Scan begrenzt statt die ganze Tabelle zu laden."""
    cols = _LIST_COLS_RUNTIME if include_runtime else _LIST_COLS
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            f"SELECT {cols} FROM process_tickets WHERE {_ACTIVE_CLAUSE} "
            "ORDER BY updated_at DESC LIMIT %s",
            (limit,),
        )
    finally:
        conn.close()
    return [_row_to_list_dict(r) for r in rows]


def _group_count(conn, column: str, *, active_only: bool = False) -> dict[str, int]:
    """COUNT/GROUP BY in der DB – es werden nur Schlüssel und Anzahl übertragen,
    keine Zeilen. `column` ist immer ein Literal aus diesem Modul (kein
    Nutzer-Input), daher keine Injektionsfläche."""
    clause = f" WHERE {_ACTIVE_CLAUSE}" if active_only else ""
    rows = _fetchall(
        conn,
        f"SELECT {column} AS k, COUNT(*) AS n FROM process_tickets{clause} GROUP BY {column}",
    )
    return {(r["k"] or "unbekannt"): int(r["n"]) for r in rows}


def count_by_status(active_only: bool = False) -> dict[str, int]:
    """Anzahl der Aufträge je Status (SQL-seitig gruppiert)."""
    conn = get_connection()
    try:
        return _group_count(conn, "status", active_only=active_only)
    finally:
        conn.close()


def metrics_snapshot(now: str) -> dict:
    """Alle Kennzahlen für die Prometheus-Gauges in EINER Verbindung.

    Getrennte Aufrufe würden den Pool je Sammellauf mehrfach belegen; alle
    Abfragen sind Aggregate (COUNT/MIN/GROUP BY), es werden also keine Zeilen –
    und erst gar keine JSON-Blobs – übertragen.
    """
    conn = get_connection()
    try:
        by_status = _group_count(conn, "status")
        by_priority = _group_count(conn, "priority")
        by_process = _group_count(conn, "process_key")
        active_row = _fetchone(
            conn, f"SELECT COUNT(*) AS n FROM process_tickets WHERE {_ACTIVE_CLAUSE}")
        oldest_rows = _fetchall(
            conn,
            "SELECT process_key, MIN(created_at) AS oldest FROM process_tickets "
            f"WHERE {_ACTIVE_CLAUSE} GROUP BY process_key",
        )
        due_row = _fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM process_tickets WHERE next_timer_due_at IS NOT NULL "
            f"AND next_timer_due_at <= %s AND {_ACTIVE_CLAUSE}",
            (to_db_datetime(now),),
        )
    finally:
        conn.close()
    oldest = {}
    for r in oldest_rows:
        v = r.get("oldest")
        key = r.get("process_key") or "unbekannt"
        oldest[key] = v.isoformat() if hasattr(v, "isoformat") else v
    return {
        "total": sum(by_status.values()),
        "active": int(active_row["n"]) if active_row else 0,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_process": by_process,
        # ISO-Zeitstempel des ältesten offenen Auftrags je Prozess (Staus sichtbar
        # machen); die Alters-Rechnung passiert im Metrik-Modul.
        "oldest_active_created_at": oldest,
        "timers_due": int(due_row["n"]) if due_row else 0,
    }


# ── Laufzeit-Aggregate: aktuelle Phase & Fachabteilungen ─────────────────────
#
# Phasen- und Abteilungs-Stand stehen NUR im `runtime_json`. Damit dafür nicht
# bei jedem Sammellauf (alle 10 s) die ganze Tabelle samt Blobs durch Python
# muss, übernimmt die DB zwei Schritte:
#   * Einschränkung auf nicht-terminale Aufträge – archivierte/abgelehnte stehen
#     in keiner Phase mehr und haben keine offenen Abteilungen.
#   * Herausschneiden NUR der aktuellen Phase (Index steht im Dokument selbst):
#     Phasen-Key und deren Abteilungs-Liste. Über die Leitung geht damit je
#     Auftrag ein kurzer String statt des kompletten Ablaufzustands.
# Vollständig in SQL zu gruppieren ginge nur mit JSON_TABLE (MariaDB 10.6+) –
# eine härtere Versions-Anforderung als der Rest des Schemas stellt. Die hier
# benutzten JSON-Pfad-Funktionen gibt es seit MariaDB 10.2.
#
# `values_json` wird bewusst NICHT gelesen: Metrik-Reihen haben keinen
# Sichtbarkeitsfilter, Feldwerte haben in ihnen nichts verloren.


def _current_phase_path(suffix: str) -> str:
    """SQL-Ausdruck für den JSON-Pfad auf ein Feld der AKTUELLEN Phase."""
    return ("CONCAT('$.phases[', JSON_EXTRACT(runtime_json, '$.current_index'), "
            f"'].{suffix}')")


ACTIVE_RUNTIME_SQL = (
    "SELECT process_key, "
    f"JSON_UNQUOTE(JSON_EXTRACT(runtime_json, {_current_phase_path('key')})) AS phase_key, "
    f"JSON_EXTRACT(runtime_json, {_current_phase_path('departments')}) AS departments_json "
    f"FROM process_tickets WHERE {_ACTIVE_CLAUSE}"
)


def active_runtime_rows() -> list[dict]:
    """Prozess-Key, aktuelle Phase und Abteilungs-Stand JEDES aktiven Auftrags.

    Bewusst OHNE LIMIT: das Ergebnis ist eine Kennzahl – ein abgeschnittenes
    Ergebnis wäre nicht „ungenau", sondern falsch. Begrenzt wird stattdessen die
    Menge (nur aktive Aufträge) und die Breite (zwei kurze Spalten je Zeile).
    """
    conn = get_connection()
    try:
        rows = _fetchall(conn, ACTIVE_RUNTIME_SQL)
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            depts = json.loads(r["departments_json"]) if r.get("departments_json") else []
        except (ValueError, TypeError):
            # Ein kaputter Ablaufzustand darf die Kennzahlen aller anderen
            # Aufträge nicht mitnehmen.
            depts = []
        out.append({
            "process_key": r.get("process_key") or "unbekannt",
            "phase_key": r.get("phase_key") or "unbekannt",
            "departments": depts if isinstance(depts, list) else [],
        })
    return out


# ── Admin-Notfalleingriff ─────────────────────────────────────────────────────

def delete(ticket_id: int) -> bool:
    """Auftrag samt Verlauf, Beobachtern und Timer-Sperren löschen.

    Nur für Admins gedacht (Fehleingaben, Testdaten). Das AUDIT bleibt bestehen –
    es liegt in einer eigenen, append-only Tabelle und überlebt die Löschung
    bewusst; sonst wäre nicht mehr nachvollziehbar, dass es den Auftrag gab.

    Die Nummern-Ansprüche (`process_sequence_claims`) bleiben ebenfalls stehen:
    eine einmal vergebene Personalnummer darf nicht recycelt werden.
    """
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT id FROM process_tickets WHERE id = %s", (ticket_id,))
        if not row:
            return False
        _exec(conn, "DELETE FROM process_ticket_events WHERE ticket_id = %s", (ticket_id,))
        _exec(conn, "DELETE FROM process_ticket_watchers WHERE ticket_id = %s", (ticket_id,))
        _exec(conn, "DELETE FROM process_timer_fires WHERE ticket_id = %s", (ticket_id,))
        _exec(conn, "DELETE FROM process_tickets WHERE id = %s", (ticket_id,))
        conn.commit()
    finally:
        conn.close()
    return True
