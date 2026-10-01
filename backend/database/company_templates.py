"""Firmen-Dokument-Vorlagen (.docx/PDF) je (Firma, Name) – Grundlage für
firmenabhängige Dokumente (Arbeitsvertrag, Kündigung …).

Anders als die prozessgebundene Vorlage (process_document_templates) hängt diese
Vorlage an der FIRMA: eine Firma kann beliebig viele benannte Vorlagen tragen
(Name = z. B. „Arbeitsvertrag", „Kündigung"). Ein Prozess-Dokument verweist nur
über den NAMEN darauf; welche Datei wirklich gefüllt wird, entscheidet die im
Auftrag gewählte Firma. Marker-Zuordnungen/Bedingungen bleiben im Prozess (eine
Konvention je Vorlagen-Typ). Der Blob liegt über services/attachment_storage auf
der Platte; hier nur Metadaten + `stored_path`.
"""
from typing import Optional

from backend.database.connection import _exec, _fetchall, _fetchone, get_connection

COMPANY_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS company_document_templates (
    company           VARCHAR(255) NOT NULL,
    name              VARCHAR(150) NOT NULL,
    stored_path       VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    content_type      VARCHAR(150),
    size_bytes        BIGINT NOT NULL DEFAULT 0,
    uploaded_by_id    VARCHAR(150),
    uploaded_by_name  VARCHAR(255),
    uploaded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_COLS = ("company, name, stored_path, original_filename, content_type, size_bytes, "
         "uploaded_by_id, uploaded_by_name, uploaded_at")


def get_template(company: str, name: str) -> Optional[dict]:
    conn = get_connection()
    try:
        return _fetchone(
            conn,
            f"SELECT {_COLS} FROM company_document_templates WHERE company=%s AND name=%s",
            (company, name))
    finally:
        conn.close()


def list_for_company(company: str) -> list[dict]:
    """Alle Vorlagen einer Firma (für Verwaltung im Companies-Panel)."""
    conn = get_connection()
    try:
        return _fetchall(
            conn,
            f"SELECT {_COLS} FROM company_document_templates WHERE company=%s ORDER BY name",
            (company,))
    finally:
        conn.close()


def list_all() -> list[dict]:
    conn = get_connection()
    try:
        return _fetchall(
            conn,
            f"SELECT {_COLS} FROM company_document_templates ORDER BY company, name", ())
    finally:
        conn.close()


def set_template(*, company: str, name: str, stored_path: str, original_filename: str,
                 content_type: Optional[str], size_bytes: int,
                 uploaded_by_id: Optional[str], uploaded_by_name: Optional[str]) -> dict:
    """Vorlage setzen/ersetzen (eine je Firma+Name). Gibt die neue Zeile zurück."""
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO company_document_templates "
              "(company, name, stored_path, original_filename, content_type, size_bytes, "
              " uploaded_by_id, uploaded_by_name) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
              "ON DUPLICATE KEY UPDATE stored_path=VALUES(stored_path), "
              "original_filename=VALUES(original_filename), content_type=VALUES(content_type), "
              "size_bytes=VALUES(size_bytes), uploaded_by_id=VALUES(uploaded_by_id), "
              "uploaded_by_name=VALUES(uploaded_by_name), uploaded_at=CURRENT_TIMESTAMP",
              (company, name, stored_path, original_filename, content_type, size_bytes,
               uploaded_by_id, uploaded_by_name))
        conn.commit()
    finally:
        conn.close()
    return get_template(company, name)


def delete_template(company: str, name: str) -> Optional[dict]:
    """Vorlage-Datensatz entfernen; gibt die alte Zeile zurück (für Blob-Cleanup)."""
    row = get_template(company, name)
    conn = get_connection()
    try:
        _exec(conn,
              "DELETE FROM company_document_templates WHERE company=%s AND name=%s",
              (company, name))
        conn.commit()
    finally:
        conn.close()
    return row
