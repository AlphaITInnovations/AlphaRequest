"""
Metadaten der Datei-Anhänge (die Blobs liegen auf dem Dateisystem, siehe
backend/services/attachment_storage.py).

Versionierung: gleiche „logische" Datei erneut hochladen → neue Version derselben
`family_id` (alte bleibt, is_current=0). Löschen = Soft-Delete (deleted_at) – die
Zeile bleibt für die Nachverfolgung erhalten, der Blob wird entfernt.

Zwei Welten an EINER Tabelle: Anhänge gehören entweder zu einem Alt-Ticket
(`tickets`) oder zu einem Prozess-Ticket (`process_tickets`). Unterschieden wird
über `entity_type` ('ticket' | 'process_ticket'); die Spalte `ticket_id` heißt aus
Kompatibilitätsgründen weiter so, bedeutet aber „ID der Entität vom Typ
`entity_type`". Eine Umbenennung würde jeden bestehenden Aufrufer brechen und den
Cutover des Alt-Systems unnötig verkomplizieren – der Name bleibt, die Bedeutung
steht hier. `field_key` bindet eine Datei an ein konkretes Anhang-Feld der
Prozess-Definition (NULL = allgemeiner Anhang).
"""

import uuid
from typing import List, Optional, Tuple

from backend.database.connection import get_connection, _exec, _fetchone, _fetchall


ATTACHMENTS_DDL = """
CREATE TABLE IF NOT EXISTS attachments (
    id                BIGINT        NOT NULL AUTO_INCREMENT,
    entity_type       VARCHAR(32)   NOT NULL DEFAULT 'ticket',
    ticket_id         BIGINT        NULL,
    field_key         VARCHAR(255)  NULL,
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
    INDEX idx_att_entity (entity_type, ticket_id),
    INDEX idx_att_uploaded (uploaded_at),
    INDEX idx_att_family (family_id, version),
    INDEX idx_att_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# Idempotente In-Place-Migrationen (für bereits bestehende Tabellen). Additiv:
# `entity_type` bekommt den Default 'ticket', damit JEDE bestehende Zeile ohne
# Backfill weiterhin korrekt dem Alt-System zugeordnet bleibt.
ATTACHMENTS_MIGRATIONS = [
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS entity_type VARCHAR(32) NOT NULL DEFAULT 'ticket'",
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS field_key VARCHAR(255) NULL",
    "ALTER TABLE attachments ADD INDEX IF NOT EXISTS idx_att_entity (entity_type, ticket_id)",
]

# Anhänge des Alt-Systems – Default für alle Funktionen, damit bestehende
# Aufrufer unverändert weiterlaufen.
ENTITY_TICKET = "ticket"
ENTITY_PROCESS_TICKET = "process_ticket"

_COLS = (
    "id, entity_type, ticket_id, field_key, phase_key, family_id, version, is_current, "
    "original_filename, stored_path, content_type, size_bytes, sha256, uploaded_by_id, "
    "uploaded_by_name, uploaded_at, deleted_at"
)


def insert_attachment(*, ticket_id: Optional[int], phase_key: Optional[str],
                      family_id: Optional[str], original_filename: str, stored_path: str,
                      content_type: Optional[str], size_bytes: int, sha256: Optional[str],
                      uploaded_by_id: Optional[str], uploaded_by_name: Optional[str],
                      entity_type: str = ENTITY_TICKET,
                      field_key: Optional[str] = None) -> dict:
    """Legt eine Anhang-Version an. Ohne `family_id` = neue Datei (Version 1); mit
    `family_id` = neue Version (bisherige verlieren is_current).

    `entity_type`/`field_key` siehe Modul-Docstring; `ticket_id` ist die ID der
    Entität vom Typ `entity_type`."""
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
            "(entity_type, ticket_id, field_key, phase_key, family_id, version, is_current, "
            " original_filename, stored_path, content_type, size_bytes, sha256, "
            " uploaded_by_id, uploaded_by_name, uploaded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (entity_type, ticket_id, field_key, phase_key, family_id, version,
             original_filename, stored_path, content_type, size_bytes, sha256,
             uploaded_by_id, uploaded_by_name),
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


def list_for_ticket(ticket_id: int, *, include_versions: bool = False,
                    entity_type: str = ENTITY_TICKET,
                    field_key: Optional[str] = None) -> List[dict]:
    """Anhänge EINER Entität (nicht gelöscht). Standard: nur aktuelle Versionen.

    `entity_type` ist bewusst ein expliziter Parameter mit Default 'ticket': so
    mischen sich Alt-Tickets und Prozess-Tickets NIE versehentlich, obwohl beide
    Welten dieselbe Tabelle und denselben ID-Raum-Namen (`ticket_id`) benutzen –
    Ticket #7 und Prozess-Ticket #7 existieren gleichzeitig.

    `field_key=None` heißt hier „kein Filter" (alle Anhänge der Entität), NICHT
    „nur allgemeine Anhänge" – für Letzteres gibt es count_for_field."""
    where = "entity_type=%s AND ticket_id=%s AND deleted_at IS NULL"
    params: tuple = (entity_type, ticket_id)
    if field_key is not None:
        where += " AND field_key=%s"
        params += (field_key,)
    if not include_versions:
        where += " AND is_current=1"
    conn = get_connection()
    try:
        return _fetchall(conn, f"SELECT {_COLS} FROM attachments WHERE {where} ORDER BY uploaded_at DESC", params)
    finally:
        conn.close()


def count_for_field(entity_type: str, entity_id: int, field_key: Optional[str]) -> int:
    """Anzahl aktueller (nicht gelöschter) Anhänge an EINEM Feld einer Entität.

    Anders als bei list_for_ticket bedeutet `field_key=None` hier „allgemeine
    Anhänge" (field_key IS NULL) – die Funktion beantwortet die Frage „liegt an
    genau diesem Feld eine Datei?" (z. B. für Pflicht-Anhang-Prüfungen)."""
    where = "entity_type=%s AND ticket_id=%s AND deleted_at IS NULL AND is_current=1"
    params: tuple = (entity_type, entity_id)
    if field_key is None:
        where += " AND field_key IS NULL"
    else:
        where += " AND field_key=%s"
        params += (field_key,)
    conn = get_connection()
    try:
        row = _fetchone(conn, f"SELECT COUNT(*) AS c FROM attachments WHERE {where}", params)
        return int(row["c"]) if row else 0
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
