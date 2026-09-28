"""Ausgelieferte Start-Daten (Seeds) – heute die zehn Prozess-Definitionen.

Warum unter `backend/` und nicht unter `docs/`: das Backend-Image entsteht mit
Build-Kontext `backend/` (backend/Dockerfile: `COPY requirements.txt .` – eine
requirements.txt gibt es NUR in backend/, und `COPY . ./backend/` ergibt nur mit
diesem Kontext den Importpfad `backend.main`). Alles außerhalb von `backend/`
liegt damit nicht im Image; ein Seeder, der aus `docs/` liest, liefe im Container
ins Leere.

Der Pfad wird relativ zu `__file__` gebildet – das cwd ist beim Containerstart
und beim Skriptaufruf verschieden.
"""
from pathlib import Path

#: Verzeichnis mit den ausgelieferten Prozess-Definitionen (eine JSON je Prozess).
PROCESS_SEED_DIR: Path = Path(__file__).resolve().parent / "processes"


def process_seed_files() -> list[Path]:
    """Alle Prozess-Seeds, stabil sortiert (damit Läufe vergleichbar bleiben)."""
    return sorted(PROCESS_SEED_DIR.glob("*.json"))
