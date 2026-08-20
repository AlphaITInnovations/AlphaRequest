"""Dokument-Vorlage (.docx) je Prozess – Grundlage der Dokument-Phase.

Genau EINE Vorlage je Prozess-Schlüssel. Sie ist installationsspezifisch (der
echte Vertrag) und liegt daher NICHT im Seed/Git, sondern wird pro Installation
hochgeladen. Der Blob liegt über services/attachment_storage auf der Platte;
hier nur die Metadaten + `stored_path`. Beim Export füllt services/docx_fill die
`{{marker}}` der Vorlage aus den Auftragswerten.
"""
from typing import Optional

from backend.database.connection import _exec, _fetchone, get_connection

PROCESS_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS process_document_templates (
    process_key       VARCHAR(150) PRIMARY KEY,
    stored_path       VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    content_type      VARCHAR(150),
    size_bytes        BIGINT NOT NULL DEFAULT 0,
    uploaded_by_id    VARCHAR(150),
    uploaded_by_name  VARCHAR(255),
    uploaded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_COLS = ("process_key, stored_path, original_filename, content_type, size_bytes, "
         "uploaded_by_id, uploaded_by_name, uploaded_at")


def get_template(process_key: str) -> Optional[dict]:
    conn = get_connection()
    try:
        return _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_document_templates WHERE process_key=%s",
            (process_key,))
    finally:
        conn.close()


def set_template(*, process_key: str, stored_path: str, original_filename: str,
                 content_type: Optional[str], size_bytes: int,
                 uploaded_by_id: Optional[str], uploaded_by_name: Optional[str]) -> dict:
    """Vorlage setzen/ersetzen (eine je Prozess). Gibt die neue Zeile zurück."""
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO process_document_templates "
              "(process_key, stored_path, original_filename, content_type, size_bytes, "
              " uploaded_by_id, uploaded_by_name) VALUES (%s,%s,%s,%s,%s,%s,%s) "
              "ON DUPLICATE KEY UPDATE stored_path=VALUES(stored_path), "
              "original_filename=VALUES(original_filename), content_type=VALUES(content_type), "
              "size_bytes=VALUES(size_bytes), uploaded_by_id=VALUES(uploaded_by_id), "
              "uploaded_by_name=VALUES(uploaded_by_name), uploaded_at=CURRENT_TIMESTAMP",
              (process_key, stored_path, original_filename, content_type, size_bytes,
               uploaded_by_id, uploaded_by_name))
        conn.commit()
    finally:
        conn.close()
    return get_template(process_key)


def delete_template(process_key: str) -> Optional[dict]:
    """Vorlage-Datensatz entfernen; gibt die alte Zeile zurück (für Blob-Cleanup)."""
    row = get_template(process_key)
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM process_document_templates WHERE process_key=%s",
              (process_key,))
        conn.commit()
    finally:
        conn.close()
    return row
