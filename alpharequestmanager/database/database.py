import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy.engine import make_url


from alpharequestmanager.models.models import Ticket, RequestStatus, TicketType
from alpharequestmanager.utils.logger import logger


# ============================================================
# Helpers
# ============================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_json(raw: Optional[str], fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


# ============================================================
# DB Connection
# ============================================================

def get_connection():
    """Create MariaDB connection from DSN."""
    dsn = os.getenv("MARIADB_DSN")
    url = make_url(dsn)

    return pymysql.connect(
        host=url.host,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.database,
        cursorclass=DictCursor,
        autocommit=False,
        charset=url.query.get("charset", ["utf8mb4"])[0],
    )


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


# ============================================================
# Schema Management
# ============================================================

TICKET_TABLE = "tickets"

TICKET_FIELDS = """
id, title, ticket_type, description,
owner_id, owner_name, owner_info,
comment, status, priority,
created_at, updated_at,
ninja_metadata,
assignee_id, assignee_name, assignee_history,
assignee_group_id, assignee_group_name,
tags
"""


def init_db():
    logger.info("Initializing database (MariaDB)")

    ddl_tickets = f"""
    CREATE TABLE IF NOT EXISTS {TICKET_TABLE} (
        id                  INT AUTO_INCREMENT PRIMARY KEY,

        title               TEXT NOT NULL,
        description         LONGTEXT NOT NULL,
        ticket_type         VARCHAR(255) NOT NULL,
        owner_id            VARCHAR(255) NOT NULL,
        owner_name          VARCHAR(255) NOT NULL,
        owner_info          LONGTEXT NULL,

        comment             LONGTEXT NULL,
        status              VARCHAR(64) NOT NULL,
        priority            VARCHAR(64) DEFAULT 'medium',

        created_at          VARCHAR(64) NOT NULL,
        updated_at          VARCHAR(64) NULL,

        ninja_metadata      LONGTEXT NULL,

        assignee_id         VARCHAR(255) NULL,
        assignee_name       VARCHAR(255) NULL,
        assignee_history    LONGTEXT NULL,

        assignee_group_id   VARCHAR(255) NULL,
        assignee_group_name VARCHAR(255) NULL,

        tags                LONGTEXT NULL
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


# ============================================================
# Ticket CRUD
# ============================================================

def insert_ticket(
    title: str,
    ticket_type: TicketType,
    description: str,
    owner_id: str,
    owner_name: str,
    owner_info: str,
    ninja_metadata: Optional[str] = None,
    priority: str = "medium",
    tags: Optional[List[str]] = None
) -> int:

    now = _now_iso()
    tags_json = json.dumps(tags or [], ensure_ascii=False)

    conn = get_connection()
    try:
        cur = _exec(conn, f"""
            INSERT INTO {TICKET_TABLE} (
                title, ticket_type, description, 
                owner_id, owner_name, owner_info,
                comment, status, priority,
                created_at, updated_at,
                ninja_metadata,
                assignee_id, assignee_name, assignee_history,
                assignee_group_id, assignee_group_name,
                tags
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, NULL,
                %s,
                NULL, NULL, NULL,
                NULL, NULL,
                %s
            )
        """, (
            title, ticket_type.value, description,
            owner_id, owner_name, owner_info,
            "", RequestStatus.pending.value, priority,
            now,
            ninja_metadata,
            tags_json
        ))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _select_tickets(where_sql: str = "", params: Tuple = ()) -> List[Ticket]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, f"""
            SELECT {TICKET_FIELDS}
            FROM {TICKET_TABLE}
            {where_sql}
            ORDER BY created_at DESC
        """, params)
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()


def list_all_tickets() -> List[Ticket]:
    return _select_tickets()


def list_pending_tickets() -> List[Ticket]:
    return _select_tickets("WHERE status = %s", (RequestStatus.pending.value,))


def list_tickets_by_owner(owner_id: str) -> List[Ticket]:
    return _select_tickets("WHERE owner_id = %s", (owner_id,))


def list_tickets_by_assignee(assignee_id: str) -> List[Ticket]:
    return _select_tickets("WHERE assignee_id = %s", (assignee_id,))


def get_ticket(ticket_id: int) -> Optional[Ticket]:
    rows = _select_tickets("WHERE id = %s LIMIT 1", (ticket_id,))
    return rows[0] if rows else None

def list_tickets_by_assignee_group(group_id: str) -> list[Ticket]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, f"""
            SELECT {TICKET_FIELDS}
            FROM tickets
            WHERE assignee_group_id = %s
            ORDER BY created_at DESC
        """, (group_id,))
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# Update operations
# ============================================================

def update_ticket(ticket_id: int, **fields) -> None:
    """Generic update — accepts ANY Ticket model field."""

    allowed = {
        "title", "description", "owner_id", "owner_name",
        "owner_info", "comment", "status", "priority",
        "ninja_metadata", "assignee_id", "assignee_name",
        "assignee_history", "assignee_group_id", "assignee_group_name",
        "tags"
    }

    updates = {k: v for k, v in fields.items() if k in allowed}

    if not updates:
        return

    updates["updated_at"] = _now_iso()

    set_sql = ", ".join(f"{k}=%s" for k in updates.keys())
    params = tuple(
        json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        for v in updates.values()
    ) + (ticket_id,)

    conn = get_connection()
    try:
        _exec(conn, f"UPDATE {TICKET_TABLE} SET {set_sql} WHERE id=%s", params)
        conn.commit()
    finally:
        conn.close()


def set_assignee(ticket_id: int, user_id: str, user_name: str):
    """Append to history and set assignment."""

    ticket = get_ticket(ticket_id)
    history = ticket.assignee_history_parsed if ticket else []

    history.append({
        "user_id": user_id,
        "user_name": user_name,
        "timestamp": _now_iso()
    })

    update_ticket(
        ticket_id,
        assignee_id=user_id,
        assignee_name=user_name,
        assignee_history=json.dumps(history, ensure_ascii=False)
    )


def set_assignee_group(ticket_id: int, group_id: str, group_name: str):
    update_ticket(
        ticket_id,
        assignee_group_id=group_id,
        assignee_group_name=group_name
    )


def update_ticket_metadata(
    ticket_id: int,
    ninja_ticket_id: Optional[int] = None,
    synced_at: Optional[str] = None
):
    ticket = get_ticket(ticket_id)
    metadata = ticket.metadata if ticket else {}

    if ninja_ticket_id is not None:
        metadata["ninja_ticket_id"] = ninja_ticket_id

    metadata["synced_at"] = synced_at if synced_at else _now_iso()

    update_ticket(ticket_id, ninja_metadata=json.dumps(metadata, ensure_ascii=False))


def delete_ticket(ticket_id: int) -> bool:
    conn = get_connection()
    try:
        cur = _exec(conn, f"DELETE FROM {TICKET_TABLE} WHERE id=%s", (ticket_id,))
        affected = cur.rowcount
        conn.commit()
        return affected > 0
    finally:
        conn.close()


# ============================================================
# Settings Table
# ============================================================

def settings_get(key: str, default=None) -> Any:
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT value FROM settings WHERE `key`=%s", (key,))
        if not row:
            return default
        return _parse_json(row["value"], row["value"])
    finally:
        conn.close()


def settings_set(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
              "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
              (key, payload))
        conn.commit()
    finally:
        conn.close()


def settings_all() -> Dict[str, Any]:
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT `key`,`value` FROM settings")
        return {r["key"]: _parse_json(r["value"], r["value"]) for r in rows}
    finally:
        conn.close()


# ============================================================
# Companies
# ============================================================

def get_companies() -> List[str]:
    val = settings_get("COMPANIES")
    if not val:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def set_companies(companies: List[str]):
    settings_set("COMPANIES", companies)


# ============================================================
# Ninja Token
# ============================================================

def get_ninja_token() -> Optional[dict]:
    tok = settings_get("NINJA_TOKEN")
    return tok if isinstance(tok, dict) else None


def set_ninja_token(token: Optional[dict]):
    settings_set("NINJA_TOKEN", token)


# ============================================================
# Ticket Permissions
# ============================================================

def load_ticket_permissions() -> dict:
    data = settings_get("TICKET_PERMISSIONS", {})
    if not isinstance(data, dict):
        return {}
    return {k: v if isinstance(v, list) else [] for k, v in data.items()}


def save_ticket_permissions(data: dict):
    if not isinstance(data, dict):
        raise ValueError("permissions must be dict")
    clean = {k: [str(x) for x in v] if isinstance(v, list) else [] for k, v in data.items()}
    settings_set("TICKET_PERMISSIONS", clean)


def get_groups() -> List[dict]:
    groups = settings_get("TICKET_GROUPS", default=[])
    if not isinstance(groups, list):
        return []
    return groups


def save_groups(groups: List[dict]):
    if not isinstance(groups, list):
        raise ValueError("Groups must be list")
    settings_set("TICKET_GROUPS", groups)
