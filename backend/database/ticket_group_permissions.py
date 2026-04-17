"""
Speichert welche AD-Gruppen welche Ticket-Typen erstellen dürfen.

Tabelle: ticket_group_permissions
  - ticket_type  VARCHAR(100)  (z.B. "zugang-beantragen")
  - group_id     VARCHAR(255)  (Azure AD Group Object ID)
  - PRIMARY KEY (ticket_type, group_id)
"""

from backend.database.connection import get_connection, _exec, _fetchall


# ── DDL ───────────────────────────────────────────────────────────────────────

TICKET_GROUP_PERMISSIONS_DDL = """
CREATE TABLE IF NOT EXISTS ticket_group_permissions (
    ticket_type  VARCHAR(100)  NOT NULL,
    group_id     VARCHAR(255)  NOT NULL,
    PRIMARY KEY (ticket_type, group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table():
    conn = get_connection()
    try:
        _exec(conn, TICKET_GROUP_PERMISSIONS_DDL)
        conn.commit()
    finally:
        conn.close()


# ── Read ──────────────────────────────────────────────────────────────────────

def load_all() -> dict[str, list[str]]:
    """
    Gibt alle Gruppen-Permissions zurück.
    { "zugang-beantragen": ["group-id-1", "group-id-2"], ... }
    """
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT ticket_type, group_id FROM ticket_group_permissions")
    finally:
        conn.close()

    result: dict[str, list[str]] = {}
    for row in rows:
        tt = row["ticket_type"]
        gid = row["group_id"]
        result.setdefault(tt, []).append(gid)
    return result


def get_groups_for_type(ticket_type: str) -> list[str]:
    """Gibt alle berechtigten Gruppen-IDs für einen Tickettyp zurück."""
    conn = get_connection()
    try:
        rows = _fetchall(
            conn,
            "SELECT group_id FROM ticket_group_permissions WHERE ticket_type = %s",
            (ticket_type,),
        )
    finally:
        conn.close()
    return [r["group_id"] for r in rows]


# ── Write ─────────────────────────────────────────────────────────────────────

def set_groups_for_type(ticket_type: str, group_ids: list[str]) -> None:
    """Ersetzt alle berechtigten Gruppen für einen Tickettyp."""
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM ticket_group_permissions WHERE ticket_type = %s", (ticket_type,))
        for gid in set(group_ids):
            if gid:
                _exec(
                    conn,
                    "INSERT INTO ticket_group_permissions (ticket_type, group_id) VALUES (%s, %s)",
                    (ticket_type, gid),
                )
        conn.commit()
    finally:
        conn.close()


def set_all(payload: dict[str, list[str]]) -> None:
    """
    Ersetzt alle Gruppen-Permissions komplett.
    payload: { "zugang-beantragen": ["group-id-1", ...], ... }
    """
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM ticket_group_permissions")
        for ticket_type, group_ids in payload.items():
            for gid in set(group_ids):
                if gid:
                    _exec(
                        conn,
                        "INSERT INTO ticket_group_permissions (ticket_type, group_id) VALUES (%s, %s)",
                        (ticket_type, gid),
                    )
        conn.commit()
    finally:
        conn.close()


def add_group(ticket_type: str, group_id: str) -> None:
    """Fügt eine einzelne Gruppen-Berechtigung hinzu."""
    conn = get_connection()
    try:
        _exec(
            conn,
            "INSERT IGNORE INTO ticket_group_permissions (ticket_type, group_id) VALUES (%s, %s)",
            (ticket_type, group_id),
        )
        conn.commit()
    finally:
        conn.close()


def remove_group(ticket_type: str, group_id: str) -> None:
    """Entfernt eine einzelne Gruppen-Berechtigung."""
    conn = get_connection()
    try:
        _exec(
            conn,
            "DELETE FROM ticket_group_permissions WHERE ticket_type = %s AND group_id = %s",
            (ticket_type, group_id),
        )
        conn.commit()
    finally:
        conn.close()