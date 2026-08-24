"""Gefüllte .docx → PDF über LibreOffice (headless) – originalgetreu, wie Word.

Ein browserseitiges Nachrendern (docx-preview) rechnet das Word-Layout nur nach
und paginiert unzuverlässig (falsche Seitenzahl, driftende Umbrüche). Für Vorschau
UND PDF-Export lassen wir stattdessen die echte Office-Engine im Container
konvertieren – ein Weg, der für jede beliebige .docx zuverlässig funktioniert.

`soffice` ist empfindlich gegenüber parallelen Aufrufen auf dasselbe Profil,
deshalb serialisieren wir mit einem Lock und geben jedem Lauf ein festes,
wiederverwendbares Profilverzeichnis (schnellerer Warmstart als ein frisches je
Aufruf). LibreOffice muss im Image liegen (siehe Dockerfile); fehlt es (z. B. im
lokalen Windows-Dev), wirft die Funktion eine klare ConversionError statt zu
crashen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from backend.utils.logger import logger

_LOCK = threading.Lock()
_SOFFICE = os.getenv("SOFFICE_BIN", "soffice")
_PROFILE = os.path.join(tempfile.gettempdir(), "alpharequest-lo-profile")
_TIMEOUT = int(os.getenv("DOCX_PDF_TIMEOUT", "60"))


class ConversionError(RuntimeError):
    """LibreOffice fehlt, bricht ab oder läuft in die Zeitüberschreitung."""


def convert(docx_bytes: bytes) -> bytes:
    """Wandelt .docx-Bytes in PDF-Bytes. Wirft ConversionError bei jedem Fehler."""
    with _LOCK:
        workdir = tempfile.mkdtemp(prefix="lo-")
        try:
            src = os.path.join(workdir, "document.docx")
            with open(src, "wb") as fh:
                fh.write(docx_bytes)
            cmd = [
                _SOFFICE, "--headless", "--norestore", "--invisible", "--nodefault",
                "--nolockcheck", "--nofirststartwizard",
                f"-env:UserInstallation={Path(_PROFILE).as_uri()}",
                "--convert-to", "pdf:writer_pdf_Export", "--outdir", workdir, src,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
            except FileNotFoundError as exc:
                raise ConversionError(
                    "LibreOffice (soffice) ist nicht verfügbar") from exc
            except subprocess.TimeoutExpired as exc:
                raise ConversionError(
                    "Zeitüberschreitung bei der PDF-Konvertierung") from exc

            out = os.path.join(workdir, "document.pdf")
            if proc.returncode != 0 or not os.path.exists(out):
                logger.error("soffice-Konvertierung fehlgeschlagen rc=%s: %s",
                             proc.returncode,
                             (proc.stderr or b"").decode("utf-8", "replace")[:500])
                raise ConversionError("PDF-Konvertierung fehlgeschlagen")
            with open(out, "rb") as fh:
                return fh.read()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
