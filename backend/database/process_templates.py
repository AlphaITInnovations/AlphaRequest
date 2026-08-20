"""Dokument-Vorlage (.docx) je (Prozess, Phase) – Grundlage der Dokument-Phase.

Genau EINE Vorlage je Dokument-PHASE eines Prozesses (Schlüssel:
`(process_key, phase_key)`). So kann ein Prozess mehrere Dokument-Phasen mit je
eigener .docx haben. Die Vorlage ist installationsspezifisch (der echte Vertrag)
und liegt daher NICHT im Seed/Git, sondern wird pro Installation hochgeladen. Der
Blob liegt über services/attachment_storage auf der Platte; hier nur die
Metadaten + `stored_path`. Beim Export füllt services/docx_fill die `{{marker}}`
der Vorlage aus den Auftragswerten.
"""
from typing import Optional

from backend.database.connection import _exec, _fetchall, _fetchone, get_connection

PROCESS_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS process_document_templates (
    process_key       VARCHAR(150) NOT NULL,
    phase_key         VARCHAR(150) NOT NULL,
    stored_path       VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    content_type      VARCHAR(150),
    size_bytes        BIGINT NOT NULL DEFAULT 0,
    uploaded_by_id    VARCHAR(150),
    uploaded_by_name  VARCHAR(255),
    uploaded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (process_key, phase_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

#: Umstieg „eine Vorlage je Prozess" → „eine je (Prozess, Phase)". Bestehende
#: Zeilen bekommen phase_key='' und müssen der richtigen Phase neu zugeordnet
#: (hochgeladen) werden – das Feature ist noch nicht ausgerollt, daher unkritisch.
#: DROP+ADD PRIMARY KEY ist idempotent: ein erneuter Lauf ersetzt den (bereits
#: zusammengesetzten) Schlüssel durch denselben.
PROCESS_TEMPLATES_MIGRATIONS = [
    "ALTER TABLE process_document_templates "
    "ADD COLUMN IF NOT EXISTS phase_key VARCHAR(150) NOT NULL DEFAULT ''",
    "ALTER TABLE process_document_templates "
    "DROP PRIMARY KEY, ADD PRIMARY KEY (process_key, phase_key)",
]

_COLS = ("process_key, phase_key, stored_path, original_filename, content_type, "
         "size_bytes, uploaded_by_id, uploaded_by_name, uploaded_at")


def get_template(process_key: str, phase_key: str) -> Optional[dict]:
    conn = get_connection()
    try:
        return _fetchone(
            conn,
            f"SELECT {_COLS} FROM process_document_templates "
            "WHERE process_key=%s AND phase_key=%s",
            (process_key, phase_key))
    finally:
        conn.close()


def list_templates(process_key: str) -> list[dict]:
    """Alle Vorlagen eines Prozesses (für Aufräumen bei Prozess-Löschung)."""
    conn = get_connection()
    try:
        return _fetchall(
            conn,
            f"SELECT {_COLS} FROM process_document_templates WHERE process_key=%s",
            (process_key,))
    finally:
        conn.close()


def set_template(*, process_key: str, phase_key: str, stored_path: str,
                 original_filename: str, content_type: Optional[str], size_bytes: int,
                 uploaded_by_id: Optional[str], uploaded_by_name: Optional[str]) -> dict:
    """Vorlage setzen/ersetzen (eine je Prozess+Phase). Gibt die neue Zeile zurück."""
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO process_document_templates "
              "(process_key, phase_key, stored_path, original_filename, content_type, "
              " size_bytes, uploaded_by_id, uploaded_by_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
              "ON DUPLICATE KEY UPDATE stored_path=VALUES(stored_path), "
              "original_filename=VALUES(original_filename), content_type=VALUES(content_type), "
              "size_bytes=VALUES(size_bytes), uploaded_by_id=VALUES(uploaded_by_id), "
              "uploaded_by_name=VALUES(uploaded_by_name), uploaded_at=CURRENT_TIMESTAMP",
              (process_key, phase_key, stored_path, original_filename, content_type,
               size_bytes, uploaded_by_id, uploaded_by_name))
        conn.commit()
    finally:
        conn.close()
    return get_template(process_key, phase_key)


def delete_template(process_key: str, phase_key: str) -> Optional[dict]:
    """Vorlage-Datensatz entfernen; gibt die alte Zeile zurück (für Blob-Cleanup)."""
    row = get_template(process_key, phase_key)
    conn = get_connection()
    try:
        _exec(conn,
              "DELETE FROM process_document_templates WHERE process_key=%s AND phase_key=%s",
              (process_key, phase_key))
        conn.commit()
    finally:
        conn.close()
    return row


def delete_all(process_key: str) -> list[dict]:
    """ALLE Vorlagen eines Prozesses entfernen; gibt die alten Zeilen zurück (für
    Blob-Cleanup). Für die Prozess-Löschung – sonst verwaisen Zeile und .docx auf
    der Platte und könnten einen später gleichnamigen Prozess mit einer alten
    Vorlage füllen."""
    rows = list_templates(process_key)
    conn = get_connection()
    try:
        _exec(conn, "DELETE FROM process_document_templates WHERE process_key=%s",
              (process_key,))
        conn.commit()
    finally:
        conn.close()
    return rows
