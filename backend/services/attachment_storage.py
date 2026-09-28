"""
Datei-Ablage für Anhänge: Blobs auf dem Dateisystem, Metadaten in der DB
(siehe backend/database/attachments.py).

Bewusst hinter einer schmalen Schnittstelle (save_stream / full_path / delete),
damit die Ablage später ohne Eingriff in die Fachlogik auf S3/MinIO umgestellt
werden kann. Dateien werden unter einem zufälligen UUID-Namen abgelegt (kein
Original-Name im Pfad → kein Path-Traversal, keine Kollisionen), leicht
geshardet (…/ab/abcd…), damit kein Verzeichnis Millionen Einträge bekommt.
"""

import hashlib
import os
import uuid
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from backend.utils.config import config

_CHUNK = 1024 * 1024  # 1 MiB


class FileTooLarge(Exception):
    """Upload überschreitet das erlaubte Maximum."""


def _base_dir() -> Path:
    return Path(config.ATTACHMENTS_DIR)


def save_stream(fileobj: BinaryIO, *, max_bytes: Optional[int] = None) -> Tuple[str, int, str]:
    """Speichert den Stream und gibt (stored_path, size_bytes, sha256_hex) zurück.
    `stored_path` ist relativ zum ATTACHMENTS_DIR. Überschreitet der Stream
    `max_bytes`, wird die (partielle) Datei entfernt und FileTooLarge geworfen."""
    token = uuid.uuid4().hex
    rel = f"{token[:2]}/{token}"
    dest = _base_dir() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    h = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = fileobj.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise FileTooLarge()
                out.write(chunk)
                h.update(chunk)
    except BaseException:
        # Partielle Datei nicht liegen lassen.
        try:
            if dest.is_file():
                dest.unlink()
        except Exception:
            pass
        raise
    return rel, size, h.hexdigest()


def full_path(stored_path: str) -> Path:
    """Absoluter Pfad zu einem stored_path – mit Schutz gegen Ausbrechen aus dem
    Ablage-Verzeichnis (Path-Traversal)."""
    base = _base_dir().resolve()
    p = (base / stored_path).resolve()
    if p != base and not str(p).startswith(str(base) + os.sep):
        raise ValueError("Ungültiger Attachment-Pfad")
    return p


def exists(stored_path: str) -> bool:
    try:
        return full_path(stored_path).is_file()
    except Exception:
        return False


def delete(stored_path: str) -> None:
    """Blob löschen (best-effort). Metadaten bleiben für die Nachverfolgung erhalten."""
    try:
        p = full_path(stored_path)
        if p.is_file():
            p.unlink()
    except Exception:
        pass
