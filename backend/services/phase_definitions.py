from dataclasses import dataclass
from enum import Enum
from typing import List
from backend.models.models import TicketType


class PhaseType(str, Enum):
    creation = "creation"
    assignment = "assignment"
    department_review = "department_review"


@dataclass
class PhaseDefinition:
    key: str
    label: str
    type: PhaseType


TICKET_PHASES: dict[TicketType, List[PhaseDefinition]] = {
    TicketType.zugang_beantragen: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.zugang_sperren: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.hardware: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.niederlassung_anmelden: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.niederlassung_schliessen: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.niederlassung_umzug: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.marketing_stellenanzeige: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.hotelbuchung: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("durchfuehrung", "Durchführung", PhaseType.department_review),
    ],
    TicketType.basis_ticket: [
        PhaseDefinition("erstellung", "Erstellung", PhaseType.creation),
        PhaseDefinition("bearbeitung", "Bearbeitung", PhaseType.assignment),
    ],
}
