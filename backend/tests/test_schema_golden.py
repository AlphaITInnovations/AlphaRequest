"""Forward-Compat-Schutz fürs Prozess-Schema.

Ohne versionierten Parser/Migrationspfad (Design-Doc §3.3, noch offen) wird jede
gepinnte Alt-Definition zur Laufzeit unter den AKTUELLEN Regeln neu validiert. Eine
Schema-Änderung, die eine bereits gültige Definition nicht mehr erfüllt, würde damit
laufende Tickets bricken. Diese Tests sind die Schranke:

* `test_golden_*`: eingefrorene v1-Definitionen (tests/fixtures/golden/) MÜSSEN
  weiter validieren – sie stehen für real gepinnte Alt-Definitionen. NICHT editieren
  (siehe die README dort).
* `test_ausgelieferte_*`: die tatsächlich ausgelieferten Definitionen (Seeds +
  docs/prozesse) müssen ebenfalls gültig bleiben.
"""
import json
from pathlib import Path

import pytest

from backend.schemas.process_definition import ProcessDefinition

_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _golden_files() -> list[Path]:
    return sorted(_GOLDEN_DIR.glob("*.json"))


def _shipped_files() -> list[Path]:
    seeds = sorted((_ROOT / "backend" / "seeds" / "processes").glob("*.json"))
    docs = sorted((_ROOT / "docs" / "prozesse").glob("*.json"))
    return seeds + docs


def test_golden_verzeichnis_ist_nicht_leer():
    # Schutz gegen ein versehentlich leeres/verschobenes Golden-Set (sonst grün, aber
    # ohne Abdeckung).
    assert _golden_files(), "Keine eingefrorenen Golden-Definitionen gefunden"


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.name)
def test_golden_definition_validiert_weiter(path: Path):
    """Eine eingefrorene v1-Definition MUSS unter dem aktuellen Schema gültig bleiben.
    Schlägt das fehl, bricht die Schema-Änderung bereits gepinnte Tickets."""
    ProcessDefinition.model_validate(_load(path))


@pytest.mark.parametrize("path", _shipped_files(), ids=lambda p: p.name)
def test_ausgelieferte_definition_validiert(path: Path):
    """Auch die tatsächlich ausgelieferten Definitionen (Seeds + docs/prozesse)
    müssen gültig bleiben."""
    ProcessDefinition.model_validate(_load(path))
