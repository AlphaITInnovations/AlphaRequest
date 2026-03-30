import json
from datetime import datetime
from typing import List, Optional, Tuple

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone
from backend.models.models import Ticket, RequestStatus


TICKET_TABLE = "tickets"

TICKET_FIELDS = """
id, title, ticket_type, description,
owner_id, owner_name, owner_info,
comment, status, priority,
created_at, updated_at,
ninja_metadata, workflow_state,
assignee_id, assignee_name,
accountable_id, accountable_name,
assignee_group_id, assignee_group_name,
assignment_history, history
"""

DDL_TICKETS = f"""
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
    workflow_state      LONGTEXT NULL,
    assignee_id         VARCHAR(255) NULL,
    assignee_name       VARCHAR(255) NULL,
    accountable_id      VARCHAR(255) NULL,
    accountable_name    VARCHAR(255) NULL,
    assignee_group_id   VARCHAR(255) NULL,
    assignee_group_name VARCHAR(255) NULL,
    assignment_history  LONGTEXT NULL,
    history             LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _select_tickets(
    where_sql: str = "",
    params: Tuple = (),
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[Ticket]:
    conn = get_connection()
    try:
        sql_params = list(params)
        limit_sql = ""

        if limit is not None:
            limit_sql = " LIMIT %s"
            sql_params.append(limit)
            if offset is not None:
                limit_sql += " OFFSET %s"
                sql_params.append(offset)

        rows = _fetchall(
            conn,
            f"""
            SELECT {TICKET_FIELDS}
            FROM {TICKET_TABLE}
            {where_sql}
            ORDER BY created_at DESC
            {limit_sql}
            """,
            tuple(sql_params),
        )
        return [Ticket.from_row(r) for r in rows]
    finally:
        conn.close()


def insert_ticket(
    title: str,
    ticket_type: str,
    description: str,
    owner_id: str,
    owner_name: str,
    owner_info: str,
    comment: str,
    status: str,
    ninja_metadata: Optional[str] = None,
    priority: str = "medium",
) -> int:
    now = _now_iso()
    conn = get_connection()
    try:
        cur = _exec(conn, f"""
            INSERT INTO {TICKET_TABLE} (
                title, ticket_type, description,
                owner_id, owner_name, owner_info,
                comment, status, priority,
                created_at, updated_at,
                ninja_metadata,
                assignee_id, assignee_name,
                accountable_id, accountable_name,
                assignee_group_id, assignee_group_name,
                assignment_history,
                history
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, NULL,
                %s,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL,
                %s,
                %s
            )
        """, (
            title, ticket_type, description,
            owner_id, owner_name, owner_info,
            comment, status, priority,
            now,
            ninja_metadata,
            json.dumps([], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
        ))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_all_tickets(
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> List[Ticket]:
    return _select_tickets(limit=limit, offset=offset)


def count_all_tickets() -> int:
    conn = get_connection()
    try:
        row = _fetchone(conn, f"SELECT COUNT(*) as cnt FROM {TICKET_TABLE}", ())
        return row["cnt"] if row else 0
    finally:
        conn.close()


def list_tickets_by_owner(owner_id: str) -> List[Ticket]:
    return _select_tickets("WHERE owner_id = %s", (owner_id,))


def list_tickets_by_assignee(assignee_id: str) -> List[Ticket]:
    return _select_tickets("WHERE assignee_id = %s", (assignee_id,))


def list_tickets_by_assignee_group(group_id: str) -> List[Ticket]:
    return _select_tickets(
        "WHERE assignee_group_id = %s AND status = %s",
        (group_id, RequestStatus.in_request.value),
    )


def get_ticket(ticket_id: int) -> Optional[Ticket]:
    rows = _select_tickets("WHERE id = %s", (ticket_id,), limit=1)
    return rows[0] if rows else None


def update_ticket(ticket_id: int, **fields) -> None:
    allowed = {
        "title", "description", "owner_id", "owner_name",
        "owner_info", "comment", "status", "priority",
        "ninja_metadata", "workflow_state",
        "assignee_id", "assignee_name",
        "accountable_id", "accountable_name",
        "assignee_group_id", "assignee_group_name",
        "assignment_history", "history",
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


def update_ticket_metadata(
    ticket_id: int,
    ninja_ticket_id: Optional[int] = None,
    synced_at: Optional[str] = None,
) -> None:
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


def _append_assignment_history(
    ticket_id: int,
    *,
    assignee: Optional[dict] = None,
    accountable: Optional[dict] = None,
    group: Optional[dict] = None,
    action: Optional[str] = None,
) -> None:
    ticket = get_ticket(ticket_id)
    history = ticket.assignment_history_parsed if ticket else []

    history.append({
        "timestamp": _now_iso(),
        "assignee": assignee,
        "accountable": accountable,
        "group": group,
        "action": action,
    })

    update_ticket(ticket_id, assignment_history=json.dumps(history, ensure_ascii=False))


def set_assignee(ticket_id: int, user_id: str, user_name: str) -> None:
    _append_assignment_history(
        ticket_id,
        assignee={"id": user_id, "name": user_name},
        action="set_assignee",
    )
    update_ticket(ticket_id, assignee_id=user_id, assignee_name=user_name)


def set_accountable(ticket_id: int, user_id: str, user_name: str) -> None:
    _append_assignment_history(
        ticket_id,
        accountable={"id": user_id, "name": user_name},
        action="set_accountable",
    )
    update_ticket(ticket_id, accountable_id=user_id, accountable_name=user_name)


def set_assignee_group(ticket_id: int, group_id: str, group_name: str) -> None:
    _append_assignment_history(
        ticket_id,
        group={"id": group_id, "name": group_name},
        action="set_group",
    )
    update_ticket(ticket_id, assignee_group_id=group_id, assignee_group_name=group_name)