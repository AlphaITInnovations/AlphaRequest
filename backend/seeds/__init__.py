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

#: Verzeichnis mit AUTO-VERWALTETEN Prozessen: sie werden beim Start automatisch
#: angelegt/aktualisiert (neue Version) und sind im UI schreibgeschützt – die JSON
#: ist die Wahrheit. Gedacht für Prozesse, die wir per Repo pflegen, ohne dass sie
#: nach jeder Änderung von Hand neu importiert werden müssen.
AUTO_SEED_DIR: Path = Path(__file__).resolve().parent / "auto"


def process_seed_files() -> list[Path]:
    """Alle (manuellen) Prozess-Seeds, stabil sortiert."""
    return sorted(PROCESS_SEED_DIR.glob("*.json"))


def auto_seed_files() -> list[Path]:
    """Alle auto-verwalteten Prozess-Seeds, stabil sortiert. Ordner darf fehlen."""
    return sorted(AUTO_SEED_DIR.glob("*.json")) if AUTO_SEED_DIR.is_dir() else []
