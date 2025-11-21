# File: alpharequestmanager/database.py
import json
from datetime import datetime
from .models import Ticket, RequestStatus
from .logger import logger
import pymysql
from pymysql.cursors import DictCursor
from typing import List, Optional, Any, Tuple
import os
from sqlalchemy.engine import make_url



def _now_iso() -> str:
    return datetime.utcnow().isoformat()



def get_connection():
    dsn = os.getenv("MARIADB_DSN")
    url = make_url(dsn)

    conn = pymysql.connect(
        host=url.host,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.database,
        cursorclass=DictCursor,
        autocommit=False,
        charset=url.query.get("charset", ["utf8mb4"])[0],
    )
    return conn



# --- kleine Helper ------------------------------------------------------------
def _exec(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur



def _fetchall(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = _exec(conn, sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows



def _fetchone(conn, sql: str, params: Tuple[Any, ...] = ()):
    cur = _exec(conn, sql, params)
    row = cur.fetchone()
    cur.close()
    return row



def init_db():
    logger.info("initializing database (MariaDB)")

    ddl_tickets = """
    CREATE TABLE IF NOT EXISTS tickets (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        title           TEXT         NOT NULL,
        description     TEXT         NOT NULL,
        owner_id        VARCHAR(255) NOT NULL,
        owner_name      VARCHAR(255) NOT NULL,
        owner_info      TEXT         NOT NULL,
        comment         TEXT         NOT NULL,
        status          VARCHAR(64)  NOT NULL,
        created_at      VARCHAR(64)  NOT NULL,
        ninja_metadata  LONGTEXT     DEFAULT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    ddl_settings = """
    CREATE TABLE IF NOT EXISTS settings (
        `key`   VARCHAR(255) PRIMARY KEY,
        `value` LONGTEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    conn = get_connection()
    try:
        _exec(conn, ddl_tickets)
        _exec(conn, ddl_settings)
        conn.commit()
    finally:
        conn.close()


def insert_ticket(title: str,
                  description: str,
                  owner_id: str,
                  owner_name: str,
                  owner_info,
                  ninja_metadata: str | None = None) -> int:
    comment = ""
    conn = get_connection()
    try:
        now = _now_iso()
        cur = _exec(conn, """
            INSERT INTO tickets
                (title, description, owner_id, owner_name, comment, status, created_at, owner_info, ninja_metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        return int(cur.lastrowid)
    finally:
        conn.close()



def list_all_tickets() -> list[Ticket]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, """
            SELECT id, title, description, owner_id, owner_name, comment, status, created_at, owner_info, ninja_metadata
            FROM tickets
            ORDER BY created_at DESC
        """)
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()



def list_pending_tickets() -> list[Ticket]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, """
            SELECT id, title, description, owner_id, owner_name, comment, status, created_at, owner_info, ninja_metadata
            FROM tickets
            WHERE status = %s
        """, (RequestStatus.pending.value,))
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()



def list_tickets_by_owner(owner_id: str) -> list[Ticket]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, """
            SELECT id, title, description, owner_id, owner_name, comment, status, created_at, owner_info
            FROM tickets
            WHERE owner_id = %s
            ORDER BY created_at DESC
        """, (owner_id,))
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()



def update_ticket(ticket_id: int, **fields) -> None:
    """
    Aktualisiert einen oder mehrere Spalten des Tickets mit id=ticket_id.
    """
    allowed = {"title","description","owner_id","owner_name","comment","status","created_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    params: Tuple[Any, ...] = tuple(updates.values()) + (ticket_id,)

    conn = get_connection()
    try:
        _exec(conn, f"UPDATE tickets SET {set_clause} WHERE id = %s", params)
        conn.commit()
    finally:
        conn.close()



def update_ticket_metadata(ticket_id: int, ninja_ticket_id: int | None = None, synced_at: str | None = None) -> None:
    """
    Aktualisiert die NinjaOne-Metadaten eines Tickets.
    Speichert JSON wie {"ninja_ticket_id": 1234, "synced_at": "..."} in ninja_metadata.
    """
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT ninja_metadata FROM tickets WHERE id = %s", (ticket_id,))
        metadata = {}
        raw = row["ninja_metadata"] if row else None
        if raw:
            try:
                metadata = json.loads(raw)
            except json.JSONDecodeError:
                metadata = {}

        if ninja_ticket_id is not None:
            metadata["ninja_ticket_id"] = ninja_ticket_id
        metadata["synced_at"] = synced_at if synced_at is not None else _now_iso()

        _exec(conn, "UPDATE tickets SET ninja_metadata = %s WHERE id = %s", (json.dumps(metadata), ticket_id))
        conn.commit()
    finally:
        conn.close()



def get_ticket_metadata(ticket_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT ninja_metadata FROM tickets WHERE id = %s", (ticket_id,))
        if not row:
            return None
        raw = row["ninja_metadata"]
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None
    finally:
        conn.close()



def delete_ticket(ticket_id: int) -> bool:
    """
    Löscht das Ticket mit der angegebenen ID.
    """
    conn = get_connection()
    try:
        cur = _exec(conn, "DELETE FROM tickets WHERE id = %s", (ticket_id,))
        affected = cur.rowcount
        conn.commit()
        if affected and affected > 0:
            logger.info("deleted ticket id=%s", ticket_id)
            return True
        else:
            logger.warning("no ticket found to delete id=%s", ticket_id)
            return False
    finally:
        conn.close()


def settings_get(key: str, default: object | None = None) -> object:
    """
    Holt JSON-kodierten Wert. Gibt default zurück, wenn nicht vorhanden.
    """
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT `value` FROM settings WHERE `key` = %s;", (key,))
        if not row:
            return default
        value = row["value"]
        try:
            return json.loads(value)
        except Exception:
            return value
    finally:
        conn.close()



def settings_set(key: str, value: object) -> None:
    """
    Speichert value JSON-kodiert unter key (Upsert per ON DUPLICATE KEY UPDATE).
    """
    payload = json.dumps(value, ensure_ascii=False)
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO settings(`key`, `value`) VALUES(%s, %s) "
              "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`);",
              (key, payload))
        conn.commit()
    finally:
        conn.close()



def settings_all() -> dict[str, object]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT `key`, `value` FROM settings")
        out: dict[str, object] = {}
        for r in rows:
            k = r["key"]
            v_raw = r["value"]
            try:
                out[k] = json.loads(v_raw)
            except Exception:
                out[k] = v_raw
        return out
    finally:
        conn.close()



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
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None

def get_ticket(ticket_id: int) -> Optional[Ticket]:
    """
    Holt ein einzelnes Ticket per ID.
    Gibt eine Ticket-Instanz zurück oder None, wenn kein Datensatz existiert.
    """
    conn = get_connection()
    try:
        row = _fetchone(conn, """
            SELECT
                id,
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
            WHERE id = %s
            LIMIT 1
        """, (ticket_id,))
        if not row:
            return None
        return Ticket.from_row(row)
    finally:
        conn.close()


def set_ninja_token(token: Optional[dict]) -> None:
    """
    Speichert das Token-Objekt (Dict) oder None.
    """
    settings_set("NINJA_TOKEN", token)


def set_sendeverfolgung(ticketID: int, sendeverfolgung) -> None:
    """
    Fügt 'sendeverfolgung' in die description (JSON) des Tickets ein
    und schreibt die geänderte description zurück in die DB.
    """
    ticket = get_ticket(ticketID)
    if not ticket:
        logger.warning("Ticket %s nicht gefunden", ticketID)
        return

    try:
        # description als JSON interpretieren
        desc_data = json.loads(ticket.description)
        if not isinstance(desc_data, dict):
            # falls description kein dict ist, in eines verpacken
            desc_data = {"description": ticket.description}
    except json.JSONDecodeError:
        # falls description kein JSON ist → fallback
        desc_data = {"description": ticket.description}

    # sendeverfolgung setzen / updaten
    desc_data["sendeverfolgung"] = sendeverfolgung

    # wieder zu JSON serialisieren
    new_desc = json.dumps(desc_data, ensure_ascii=False)

    # neue description in DB speichern
    update_ticket(ticketID, description=new_desc)

    logger.info("Sendeverfolgung für Ticket %s aktualisiert", ticketID)


#ticket permissions

def load_ticket_permissions() -> dict:
    """
    Lädt Ticket-Berechtigungen aus settings.TICKET_PERMISSIONS.
    Gibt stets ein dict zurück, nie None.
    """
    data = settings_get("TICKET_PERMISSIONS", default={})
    if not isinstance(data, dict):
        return {}

    # nur valid types berücksichtigen, falls jemand Müll speichert
    valid_keys = {
        "hardware",
        "niederlassungAnmeldung",
        "niederlassungAbmeldung",
        "niederlassungUmzug",
        "zugangBeantragen",
        "zugangSperren"
    }

    clean = {}
    for k in valid_keys:
        v = data.get(k, [])
        if isinstance(v, list):
            clean[k] = [str(x) for x in v]
        else:
            clean[k] = []

    return clean

def save_ticket_permissions(data: dict) -> None:
    """
    Speichert Ticket-Berechtigungen in settings.
    Erwartet dict: { ticket_type: [user_ids...] }
    """
    if not isinstance(data, dict):
        raise ValueError("permissions must be dict")

    # ensure values are lists of strings
    clean = {}
    for k, v in data.items():
        if isinstance(v, list):
            clean[k] = [str(x) for x in v]
        else:
            clean[k] = []

    settings_set("TICKET_PERMISSIONS", clean)
