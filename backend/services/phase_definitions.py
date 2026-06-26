from dataclasses import dataclass
from enum import Enum
from typing import List
from backend.models.models import TicketType


class PhaseType(str, Enum):
    creation = "creation"
    assignment = "assignment"
    department_review = "department_review"


# Frontend-Darstellung einer Phase
class PhaseView(str, Enum):
    form = "form"          # editierbares Formular
    readonly = "readonly"  # read-only Panel
    export = "export"      # Export-Ansicht (Daten + PDF-Export)
    approval = "approval"  # Freigabe-Ansicht (read-only Daten + Freigeben/Ablehnen)


@dataclass
class PhaseDefinition:
    key: str
    label: str
    type: PhaseType
    # Welche Ansicht das Frontend in dieser Phase zeigt. Default leitet sich aus
    # dem Typ ab (assignment -> Formular, sonst read-only).
    view: PhaseView | None = None
    # Optional: feste Zuweisung einer assignment-Phase an eine Gruppe (per Name).
    # build_workflow() löst den Namen auf und setzt die responsibility.
    assign_group: str | None = None

    @property
    def effective_view(self) -> PhaseView:
        if self.view is not None:
            return self.view
        return PhaseView.form if self.type == PhaseType.assignment else PhaseView.readonly


def _flow(*phases: PhaseDefinition) -> List[PhaseDefinition]:
    return list(phases)


# Wiederkehrende Phasen-Bausteine
_ERSTELLUNG   = lambda: PhaseDefinition("erstellung", "Erstellung", PhaseType.creation)
_BEARBEITUNG  = lambda: PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment)
_DURCHFUEHRUNG = lambda: PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review)


TICKET_PHASES: dict[TicketType, List[PhaseDefinition]] = {
    # Onboarding Mitarbeiter:innen – mehrstufig:
    #   Erstellung (Basisfelder) → Freigabe Herr Lutz (Mail JA/NEIN + In-App)
    #   → BackOffice (Felder + nächsten Bearbeiter wählen) → Bearbeitung → Durchführung
    TicketType.zugang_beantragen: _flow(
        _ERSTELLUNG(),
        PhaseDefinition("freigabe", "Freigabe Herr Lutz", PhaseType.assignment,
                        view=PhaseView.approval, assign_group="FreigabeHerrLutz"),
        PhaseDefinition("backoffice", "Sekretariat GL", PhaseType.assignment,
                        assign_group="Sekretariat GL"),
        _BEARBEITUNG(),
        _DURCHFUEHRUNG(),
    ),
    TicketType.zugang_sperren:         _flow(_ERSTELLUNG(), _BEARBEITUNG(), _DURCHFUEHRUNG()),
    TicketType.hardware:               _flow(_ERSTELLUNG(), _BEARBEITUNG(), _DURCHFUEHRUNG()),
    TicketType.niederlassung_anmelden: _flow(_ERSTELLUNG(), _BEARBEITUNG(), _DURCHFUEHRUNG()),
    TicketType.niederlassung_schliessen: _flow(_ERSTELLUNG(), _BEARBEITUNG(), _DURCHFUEHRUNG()),
    TicketType.niederlassung_umzug:    _flow(_ERSTELLUNG(), _BEARBEITUNG(), _DURCHFUEHRUNG()),
    TicketType.marketing_stellenanzeige: _flow(_ERSTELLUNG(), _DURCHFUEHRUNG()),
    TicketType.hotelbuchung: _flow(
        _ERSTELLUNG(),
        _DURCHFUEHRUNG(),
        # Custom-Phase: Zuweisung an die Reisestelle, PDF-Export, dann archivieren.
        PhaseDefinition("reisestelle", "Reisestelle", PhaseType.assignment,
                        view=PhaseView.export, assign_group="Reisestelle"),
    ),
    TicketType.basis_ticket:           _flow(_ERSTELLUNG(), _BEARBEITUNG()),
}
