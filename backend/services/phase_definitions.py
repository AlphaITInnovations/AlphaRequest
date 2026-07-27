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
    # Optional: erzwingt beim Aktivieren dieser Phase einen abweichenden Ticket-
    # Status (RequestStatus-Wert, z.B. "waiting_contract"). Ohne Angabe gilt die
    # Standardlogik (in_request bei department_review, sonst in_progress).
    enter_status: str | None = None

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
    # Onboarding – Prozess 1 „Einstellung Mitarbeiter:in":
    #   Erstellung (Vorgesetzte:r: Basis + Vertrauliches) → Freigabe Herr Lutz
    #   → Arbeitsvertrag erstellen/versenden (Sekretariat GL)
    #   → Warten auf Vertragsrücklauf (Sekretariat GL); beim Rücklauf wird
    #     automatisch Prozess 2 (zugang-beantragen) erzeugt und P1 archiviert.
    TicketType.einstellung: _flow(
        PhaseDefinition("erstellung", "Einstellungsdaten erfassen", PhaseType.creation),
        PhaseDefinition("freigabe", "Freigabe durch Udo Lutz", PhaseType.assignment,
                        view=PhaseView.approval, assign_group="FreigabeHerrLutz"),
        PhaseDefinition("vertrag", "Arbeitsvertrag erstellen & versenden", PhaseType.assignment,
                        assign_group="Sekretariat GL"),
        PhaseDefinition("vertragsruecklauf", "Warten auf Vertragsrücklauf", PhaseType.assignment,
                        assign_group="Sekretariat GL", enter_status="waiting_contract"),
    ),
    # Onboarding – Prozess 2 „Onboarding nach Vertragsrücklauf":
    #   Erstellung → Bearbeitung Sekretariat GL (HR-Felder) → Bearbeitung
    #   Vorgesetzte:r (IT/Signatur) → Durchführung Fachabteilungen → archiviert.
    #   Gekoppelt aus P1 gestartet (Daten übernommen, Start ab Bearbeitung
    #   Sekretariat GL) oder eigenständig angelegt.
    TicketType.zugang_beantragen: _flow(
        PhaseDefinition("erstellung", "Prozesserstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung_sgl", "Bearbeitung durch Sekretariat GL", PhaseType.assignment,
                        assign_group="Sekretariat GL"),
        PhaseDefinition("bearbeitung", "Bearbeitung durch Vorgesetzten", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung durch Fachabteilungen", PhaseType.department_review),
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
