"""
Persistenter, append-only Audit-Log. Anders als die Ticket-Historie (im
`history`-Feld des Tickets) überlebt der Audit-Log das Löschen eines Tickets –
so bleibt nachvollziehbar, WER WANN WAS gemacht hat (inkl. Löschungen, Logins,
Rollen-/Rechte-Änderungen).

Tabelle: audit_log (nie löschen, nur einfügen/lesen).
"""

import json
from typing import Optional

from backend.database.connection import get_connection, _exec, _fetchall, _fetchone
from backend.utils.logger import logger


AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    created_at  DATETIME      NOT NULL,
    actor_id    VARCHAR(255)  NULL,
    actor_name  VARCHAR(255)  NULL,
    actor_type  VARCHAR(16)   NOT NULL DEFAULT 'user',
    action      VARCHAR(64)   NOT NULL,
    entity_type VARCHAR(32)   NULL,
    entity_id   VARCHAR(255)  NULL,
    summary     VARCHAR(512)  NULL,
    details     LONGTEXT      NULL,
    ip          VARCHAR(64)   NULL,
    PRIMARY KEY (id),
    INDEX idx_audit_created (created_at),
    INDEX idx_audit_actor (actor_id),
    INDEX idx_audit_entity (entity_type, entity_id),
    INDEX idx_audit_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_connection()
    try:
        _exec(conn, AUDIT_LOG_DDL)
        conn.commit()
    finally:
        conn.close()


def record_audit(
    *,
    action: str,
    actor_id: Optional[str] = None,
    actor_name: str = "System",
    actor_type: str = "user",
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    summary: Optional[str] = None,
    details: Optional[dict] = None,
    ip: Optional[str] = None,
) -> None:
    """Schreibt einen Audit-Eintrag. Fehler brechen NIE den Aufrufer (der Audit
    darf keine Fachlogik verhindern) – sie werden nur geloggt."""
    try:
        conn = get_connection()
        try:
            _exec(
                conn,
                "INSERT INTO audit_log "
                "(created_at, actor_id, actor_name, actor_type, action, entity_type, "
                " entity_id, summary, details, ip) "
                "VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    actor_id, actor_name, actor_type, action, entity_type,
                    (str(entity_id) if entity_id is not None else None),
                    (summary or "")[:512] or None,
                    (json.dumps(details, ensure_ascii=False) if details is not None else None),
                    ip,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "Audit-Eintrag fehlgeschlagen (action=%s entity=%s/%s)", action, entity_type, entity_id
        )
        return

    logger.info(
        "AUDIT action=%s actor=%s(%s) entity=%s/%s",
        action, actor_name or "?", actor_id or "-", entity_type or "-", entity_id or "-",
    )


def list_audit(
    *,
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    q: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Gefilterte, paginierte Audit-Einträge (neueste zuerst) + Gesamtzahl."""
    where: list[str] = []
    params: list = []
    if action:
        where.append("action = %s"); params.append(action)
    if actor:
        where.append("(actor_id = %s OR actor_name LIKE %s)"); params += [actor, f"%{actor}%"]
    if entity_type:
        where.append("entity_type = %s"); params.append(entity_type)
    if entity_id:
        where.append("entity_id = %s"); params.append(str(entity_id))
    if q:
        where.append("(summary LIKE %s OR details LIKE %s OR action LIKE %s)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_connection()
    try:
        total_row = _fetchone(conn, f"SELECT COUNT(*) AS cnt FROM audit_log {clause}", tuple(params))
        total = int(total_row["cnt"]) if total_row else 0
        rows = _fetchall(
            conn,
            "SELECT id, created_at, actor_id, actor_name, actor_type, action, entity_type, "
            f"entity_id, summary, details, ip FROM audit_log {clause} "
            "ORDER BY id DESC LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset),
        )
    finally:
        conn.close()

    result: list[dict] = []
    for r in rows:
        d = dict(r)
        raw = d.get("details")
        try:
            d["details"] = json.loads(raw) if raw else {}
        except Exception:
            d["details"] = {}
        ca = d.get("created_at")
        d["created_at"] = ca.isoformat() if hasattr(ca, "isoformat") else (str(ca) if ca else "")
        result.append(d)
    return result, total


def distinct_actions() -> list[str]:
    """Alle vorkommenden Aktionen (für den Filter im Viewer)."""
    conn = get_connection()
    try:
        rows = _fetchall(conn, "SELECT DISTINCT action FROM audit_log ORDER BY action", ())
    finally:
        conn.close()
    return [r["action"] for r in rows]
