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
    stored_path       VARCHAR(255) NULL,
    original_filename VARCHAR(255) NULL,
    content_type      VARCHAR(150),
    size_bytes        BIGINT NOT NULL DEFAULT 0,
    uploaded_by_id    VARCHAR(150),
    uploaded_by_name  VARCHAR(255),
    uploaded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ref_company       VARCHAR(255) NULL,
    PRIMARY KEY (company, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

#: Verweis-Zeilen (ref_company gesetzt) tragen keine eigene Datei – `stored_path`/
#: `original_filename` müssen daher NULL dürfen. Bestandstabellen idempotent
#: nachrüsten (der Runner toleriert ein erneutes Anwenden).
COMPANY_TEMPLATES_MIGRATIONS = [
    "ALTER TABLE company_document_templates ADD COLUMN IF NOT EXISTS ref_company VARCHAR(255) NULL",
    "ALTER TABLE company_document_templates MODIFY stored_path VARCHAR(255) NULL",
    "ALTER TABLE company_document_templates MODIFY original_filename VARCHAR(255) NULL",
]

_COLS = ("company, name, stored_path, original_filename, content_type, size_bytes, "
         "uploaded_by_id, uploaded_by_name, uploaded_at, ref_company")


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
        # ref_company bewusst auf NULL: ein Datei-Upload hebt einen etwaigen
        # früheren Firmen-Verweis dieses (Firma, Typ) wieder auf.
        _exec(conn,
              "INSERT INTO company_document_templates "
              "(company, name, stored_path, original_filename, content_type, size_bytes, "
              " uploaded_by_id, uploaded_by_name, ref_company) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL) "
              "ON DUPLICATE KEY UPDATE stored_path=VALUES(stored_path), "
              "original_filename=VALUES(original_filename), content_type=VALUES(content_type), "
              "size_bytes=VALUES(size_bytes), uploaded_by_id=VALUES(uploaded_by_id), "
              "uploaded_by_name=VALUES(uploaded_by_name), uploaded_at=CURRENT_TIMESTAMP, "
              "ref_company=NULL",
              (company, name, stored_path, original_filename, content_type, size_bytes,
               uploaded_by_id, uploaded_by_name))
        conn.commit()
    finally:
        conn.close()
    return get_template(company, name)


def set_reference(company: str, name: str, ref_company: str) -> dict:
    """Eine (Firma, Typ)-Zeile als VERWEIS auf die gleichnamige Vorlage einer
    anderen Firma setzen (keine eigene Datei). Ersetzt eine etwaige eigene Datei –
    der Aufrufer räumt deren Blob auf. Gibt die neue Zeile zurück."""
    conn = get_connection()
    try:
        _exec(conn,
              "INSERT INTO company_document_templates "
              "(company, name, stored_path, original_filename, content_type, size_bytes, "
              " uploaded_by_id, uploaded_by_name, ref_company) "
              "VALUES (%s,%s,NULL,NULL,NULL,0,NULL,NULL,%s) "
              "ON DUPLICATE KEY UPDATE stored_path=NULL, original_filename=NULL, "
              "content_type=NULL, size_bytes=0, uploaded_by_id=NULL, uploaded_by_name=NULL, "
              "uploaded_at=CURRENT_TIMESTAMP, ref_company=VALUES(ref_company)",
              (company, name, ref_company))
        conn.commit()
    finally:
        conn.close()
    return get_template(company, name)


def resolve_company_template(company: str, name: str) -> Optional[dict]:
    """Die tatsächlich zu füllende Vorlagen-Zeile für (Firma, Typ) – folgt höchstens
    EINEM Firmen-Sprung je Ebene: zuerst die firmenweite Übernahme
    (documents_shared_with) der gewählten Firma, dann ein etwaiger Pro-Dokument-
    Verweis (ref_company) der so gefundenen Zeile. Gibt eine Zeile mit `stored_path`
    (echte Datei) oder None zurück. Ein Verweis-Ziel trägt per Validierung immer
    eine eigene Datei (kein Verweis-auf-Verweis) – daher genügt ein Sprung."""
    from backend.database.settings import template_source_company
    src = template_source_company(company)               # firmenweite Übernahme (ein Sprung)
    row = get_template(src, name)
    if row is not None and row.get("ref_company"):
        row = get_template(row["ref_company"], name)     # Pro-Dokument-Verweis (ein Sprung)
    # Nur eine Zeile mit echter Datei zurückgeben – ein ins Leere zeigender Verweis
    # (z. B. Ziel-Datei nachträglich entfernt) ergibt „keine Vorlage" statt Absturz.
    return row if row and row.get("stored_path") else None


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
