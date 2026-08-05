"""Kleine, DB-freie Helfer rund um Datei-Anhänge (testbar)."""

import os


def safe_filename(name: str | None) -> str:
    """Reduziert einen (potenziell manipulierten) Dateinamen auf einen sicheren
    Basisnamen: keine Pfadanteile, keine führenden Punkte, max. 255 Zeichen."""
    raw = (name or "").strip().replace("\\", "/")
    base = os.path.basename(raw).strip().strip(".")
    return (base or "datei")[:255]


def human_size(n: int | float | None) -> str:
    """Bytes menschenlesbar: 0 B, 512 B, 1.5 KB, 3.2 MB, …"""
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
