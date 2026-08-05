"""
Metadaten der Datei-Anhänge (die Blobs liegen auf dem Dateisystem, siehe
backend/services/attachment_storage.py).

Versionierung: gleiche „logische" Datei erneut hochladen → neue Version derselben
`family_id` (alte bleibt, is_current=0). Löschen = Soft-Delete (deleted_at) – die
Zeile bleibt für die Nachverfolgung erhalten, der Blob wird entfernt.
"""

import uuid
from typing import List, Optional, Tuple

from backend.database.connection import get_connection, _exec, _fetchone, _fetchall


ATTACHMENTS_DDL = """
CREATE TABLE IF NOT EXISTS attachments (
    id                BIGINT        NOT NULL AUTO_INCREMENT,
    ticket_id         BIGINT        NULL,
    phase_key         VARCHAR(64)   NULL,
    family_id         CHAR(32)      NOT NULL,
    version           INT           NOT NULL DEFAULT 1,
    is_current        TINYINT(1)    NOT NULL DEFAULT 1,
    original_filename VARCHAR(255)  NOT NULL,
    stored_path       VARCHAR(255)  NOT NULL,
    content_type      VARCHAR(150)  NULL,
    size_bytes        BIGINT        NOT NULL DEFAULT 0,
    sha256            CHAR(64)      NULL,
    uploaded_by_id    VARCHAR(64)   NULL,
    uploaded_by_name  VARCHAR(255)  NULL,
    uploaded_at       DATETIME      NOT NULL,
    deleted_at        DATETIME      NULL,
    PRIMARY KEY (id),
    INDEX idx_att_ticket (ticket_id),
    INDEX idx_att_uploaded (uploaded_at),
    INDEX idx_att_family (family_id, version),
    INDEX idx_att_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_COLS = (
    "id, ticket_id, phase_key, family_id, version, is_current, original_filename, "
    "stored_path, content_type, size_bytes, sha256, uploaded_by_id, uploaded_by_name, "
    "uploaded_at, deleted_at"
)


def insert_attachment(*, ticket_id: Optional[int], phase_key: Optional[str],
                      family_id: Optional[str], original_filename: str, stored_path: str,
                      content_type: Optional[str], size_bytes: int, sha256: Optional[str],
                      uploaded_by_id: Optional[str], uploaded_by_name: Optional[str]) -> dict:
    """Legt eine Anhang-Version an. Ohne `family_id` = neue Datei (Version 1); mit
    `family_id` = neue Version (bisherige verlieren is_current)."""
    conn = get_connection()
    try:
        if family_id:
            row = _fetchone(conn, "SELECT COALESCE(MAX(version), 0) AS v FROM attachments WHERE family_id=%s", (family_id,))
            version = (row["v"] if row else 0) + 1
            _exec(conn, "UPDATE attachments SET is_current=0 WHERE family_id=%s", (family_id,))
        else:
            family_id = uuid.uuid4().hex
            version = 1
        _exec(
            conn,
            "INSERT INTO attachments "
            "(ticket_id, phase_key, family_id, version, is_current, original_filename, "
            " stored_path, content_type, size_bytes, sha256, uploaded_by_id, uploaded_by_name, uploaded_at) "
            "VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (ticket_id, phase_key, family_id, version, original_filename, stored_path,
             content_type, size_bytes, sha256, uploaded_by_id, uploaded_by_name),
        )
        new_id = _fetchone(conn, "SELECT LAST_INSERT_ID() AS id", ())["id"]
        conn.commit()
    finally:
        conn.close()
    return get_attachment(new_id)


def get_attachment(attachment_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        return _fetchone(conn, f"SELECT {_COLS} FROM attachments WHERE id=%s", (attachment_id,))
    finally:
        conn.close()


def list_for_ticket(ticket_id: int, *, include_versions: bool = False) -> List[dict]:
    """Anhänge eines Tickets (nicht gelöscht). Standard: nur aktuelle Versionen."""
    where = "ticket_id=%s AND deleted_at IS NULL"
    if not include_versions:
        where += " AND is_current=1"
    conn = get_connection()
    try:
        return _fetchall(conn, f"SELECT {_COLS} FROM attachments WHERE {where} ORDER BY uploaded_at DESC", (ticket_id,))
    finally:
        conn.close()


def soft_delete(attachment_id: int) -> None:
    conn = get_connection()
    try:
        _exec(conn, "UPDATE attachments SET deleted_at=NOW(), is_current=0 WHERE id=%s AND deleted_at IS NULL", (attachment_id,))
        conn.commit()
    finally:
        conn.close()


def _search_where(q: Optional[str]) -> Tuple[str, tuple]:
    where = "deleted_at IS NULL"
    params: tuple = ()
    if q:
        like = f"%{q.strip()}%"
        where += " AND (original_filename LIKE %s OR uploaded_by_name LIKE %s"
        params = (like, like)
        if q.strip().isdigit():
            where += " OR ticket_id=%s"
            params += (int(q.strip()),)
        where += ")"
    return where, params


def list_all(*, q: Optional[str] = None, limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    """Admin-Übersicht: nicht gelöschte Anhänge, neueste zuerst, optional gefiltert.
    Rückgabe: (Zeilen der Seite, Gesamtzahl)."""
    where, params = _search_where(q)
    conn = get_connection()
    try:
        total_row = _fetchone(conn, f"SELECT COUNT(*) AS c FROM attachments WHERE {where}", params)
        total = total_row["c"] if total_row else 0
        rows = _fetchall(
            conn,
            f"SELECT {_COLS} FROM attachments WHERE {where} ORDER BY uploaded_at DESC LIMIT %s OFFSET %s",
            params + (limit, offset),
        )
        return rows, total
    finally:
        conn.close()


def stats() -> dict:
    """Speicher-Kennzahlen über nicht gelöschte Anhänge (effizient, nur Aggregat)."""
    conn = get_connection()
    try:
        row = _fetchone(
            conn,
            "SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes),0) AS total_bytes "
            "FROM attachments WHERE deleted_at IS NULL",
            (),
        )
        return {"count": int(row["count"]), "total_bytes": int(row["total_bytes"])} if row else {"count": 0, "total_bytes": 0}
    finally:
        conn.close()
