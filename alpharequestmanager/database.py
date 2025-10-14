# File: alpharequestmanager/database.py
import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional
from .models import Ticket, RequestStatus
from .logger import logger


def get_connection():
    conn = sqlite3.connect("data/tickets.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    logger.info("initializing database")
    conn = get_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT    NOT NULL,
        description  TEXT    NOT NULL,
        owner_id     TEXT    NOT NULL,
        owner_name   TEXT    NOT NULL,
        owner_info   TEXT    NOT NULL,
        comment      TEXT    NOT NULL,
        status       TEXT    NOT NULL,
        created_at   TEXT    NOT NULL,
        ninja_metadata TEXT  DEFAULT NULL
    );
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def insert_ticket(title: str,
                  description: str,
                  owner_id: str,
                  owner_name: str,
                  owner_info,
                  ninja_metadata: str | None = None) -> int:
    comment = ""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().isoformat()

    c.execute("""
        INSERT INTO tickets
            (title, description, owner_id, owner_name, comment, status, created_at, owner_info, ninja_metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        title,
        description,
        owner_id,
        owner_name,
        comment,
        RequestStatus.pending.value,
        now,
        owner_info,
        ninja_metadata
    ))
    conn.commit()
    ticket_id = c.lastrowid
    conn.close()
    return ticket_id


def list_all_tickets() -> list[Ticket]:
    conn = get_connection()
    rows = conn.execute("""
                        SELECT id,
                               title,
                               description,
                               owner_id,
                               owner_name,
                               comment,
                               status,
                               created_at,
                               owner_info,
                               ninja_metadata
                        FROM tickets
                        ORDER BY created_at DESC
                        """).fetchall()
    conn.close()
    return [Ticket.from_row(r) for r in rows]

def list_pending_tickets() -> list[Ticket]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, description, owner_id, owner_name, comment, status, created_at, owner_info, ninja_metadata
        FROM tickets
        WHERE status = ?
    """, (RequestStatus.pending.value,)).fetchall()
    conn.close()
    return [Ticket.from_row(r) for r in rows]

def list_tickets_by_owner(owner_id: str) -> list[Ticket]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, description, owner_id, owner_name, comment, status, created_at, owner_info
        FROM tickets
        WHERE owner_id = ?
        ORDER BY created_at DESC
    """, (owner_id,)).fetchall()
    conn.close()
    return [Ticket.from_row(r) for r in rows]

def update_ticket(ticket_id: int, **fields) -> None:
    """
    Aktualisiert einen oder mehrere Spalten des Tickets mit id=ticket_id.
    Beispiel:
        update_ticket(5, status="approved")
        update_ticket(7, status="rejected", owner_name="Max Mustermann")
    """
    # Erlaubte Spalten
    allowed = {"title","description","owner_id","owner_name", "comment","status","created_at"}
    # Filter ungültiger keys
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    # Dynamisch SET-Klausel bauen
    set_clause = ", ".join(f"{col}=?" for col in updates)
    params = list(updates.values()) + [ticket_id]
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        UPDATE tickets
        SET {set_clause}
        WHERE id = ?
    """, params)
    conn.commit()
    conn.close()



def _now_iso():
    return datetime.utcnow().isoformat()


def update_ticket_metadata(ticket_id: int, ninja_ticket_id: int | None = None, synced_at: str | None = None) -> None:
    """
    Aktualisiert die NinjaOne-Metadaten eines Tickets.
    Speichert JSON wie {"ninja_ticket_id": 1234, "synced_at": "..."} in ninja_metadata.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Existierende Metadaten laden
    row = cur.execute("SELECT ninja_metadata FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    metadata = {}
    if row and row["ninja_metadata"]:
        try:
            metadata = json.loads(row["ninja_metadata"])
        except json.JSONDecodeError:
            metadata = {}

    if ninja_ticket_id is not None:
        metadata["ninja_ticket_id"] = ninja_ticket_id
    if synced_at is not None:
        metadata["synced_at"] = synced_at
    else:
        metadata["synced_at"] = _now_iso()

    cur.execute("UPDATE tickets SET ninja_metadata = ? WHERE id = ?", (json.dumps(metadata), ticket_id))
    conn.commit()
    conn.close()


def get_ticket_metadata(ticket_id: int) -> dict | None:
    """
    Liest die NinjaOne-Metadaten eines Tickets.
    """
    conn = get_connection()
    row = conn.execute("SELECT ninja_metadata FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    conn.close()
    if row and row["ninja_metadata"]:
        try:
            return json.loads(row["ninja_metadata"])
        except json.JSONDecodeError:
            return None
    return None





def delete_ticket(ticket_id: int) -> bool:
    """
    Löscht das Ticket mit der angegebenen ID.


    Returns
    -------
    bool
    True, wenn ein Datensatz gelöscht wurde; sonst False.


    Hinweise
    --------
    - Hebt kein Exception an, wenn das Ticket nicht existiert (gibt False zurück).
    - Loggt Erfolg bzw. Nichtexistenz für spätere Nachverfolgung.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        affected = cur.rowcount # -1 vor Ausführung, danach >= 0
        conn.commit()


        if affected and affected > 0:
            logger.info("deleted ticket id=%s", ticket_id)
            return True
        else:
            logger.warning("no ticket found to delete id=%s", ticket_id)
            return False
    finally:
        conn.close()


### Settings DB
def settings_get(key: str, default: object | None = None) -> object:
    """
    Holt JSON-kodierten Wert. Gibt default zurück, wenn nicht vorhanden.
    """
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        # defensiv: falls alter Plaintext drinsteht
        return row["value"]

def settings_set(key: str, value: object) -> None:
    """
    Speichert value JSON-kodiert unter key.
    Beispiel: set_setting("COMPANIES", [{"id":1,"name":"Acme"}])
    """
    payload = json.dumps(value, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
            (key, payload),
        )
        conn.commit()

def settings_all() -> dict[str, object]:
    conn = get_connection()
    rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
    conn.close()
    return {r["key"]: json.loads(r["value_json"]) for r in rows}

def get_companies() -> List[str]:
    """
    Gibt immer eine Liste zurück:
    - [] falls kein Eintrag existiert
    - Liste mit Strings falls vorhanden
    """
    value = settings_get("COMPANIES")
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []

def set_companies(companies: List[str]) -> None:
    """Speichert eine Companies-Liste."""
    settings_set("COMPANIES", companies)


def get_ninja_token() -> Optional[dict]:
    """
    Gibt das gespeicherte Token-Objekt als Dict zurück oder None, falls nicht vorhanden/ungültig.
    """
    value = settings_get("NINJA_TOKEN")
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        # Falls in der DB ein String liegt, versuchen zu parsen
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def set_ninja_token(token: Optional[dict]) -> None:
    """
    Speichert das Token-Objekt (Dict) oder None.
    """
    settings_set("NINJA_TOKEN", token)