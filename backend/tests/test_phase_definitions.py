"""Sichert die Workflow-Definitionen (Keys, Reihenfolge, Typen, assign_groups)."""

from backend.services.phase_definitions import TICKET_PHASES, PhaseType, PhaseView
from backend.models.models import TicketType


class TestOnboardingFlow:
    def setup_method(self):
        self.flow = TICKET_PHASES[TicketType.zugang_beantragen]

    def test_phase_keys_and_order(self):
        assert [p.key for p in self.flow] == [
            "erstellung", "freigabe", "backoffice", "bearbeitung", "durchfuehrung",
        ]

    def test_phase_types(self):
        assert [p.type for p in self.flow] == [
            PhaseType.creation, PhaseType.assignment, PhaseType.assignment,
            PhaseType.assignment, PhaseType.department_review,
        ]

    def test_labels(self):
        labels = {p.key: p.label for p in self.flow}
        assert labels["erstellung"] == "Prozesserstellung"
        assert labels["freigabe"] == "Freigabe durch Udo Lutz"
        assert labels["backoffice"] == "Bearbeitung durch Sekretariat GL"
        assert labels["bearbeitung"] == "Bearbeitung durch Vorgesetzten"
        assert labels["durchfuehrung"] == "Durchführung durch Fachabteilungen"

    def test_assign_groups(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["freigabe"].assign_group == "FreigabeHerrLutz"
        assert by_key["backoffice"].assign_group == "Sekretariat GL"
        assert by_key["bearbeitung"].assign_group is None   # freie Bearbeiterwahl

    def test_freigabe_is_approval_view(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["freigabe"].effective_view == PhaseView.approval


class TestOffboardingFlow:
    def test_no_freigabe_phase(self):
        # Offboarding hat KEINE Freigabe (kein Lutz) – erstellung → bearbeitung → durchführung
        keys = [p.key for p in TICKET_PHASES[TicketType.zugang_sperren]]
        assert keys == ["erstellung", "bearbeitung", "durchfuehrung"]
        assert "freigabe" not in keys


class TestEffectiveView:
    def test_assignment_defaults_to_form(self):
        flow = TICKET_PHASES[TicketType.zugang_beantragen]
        bearbeitung = next(p for p in flow if p.key == "bearbeitung")
        assert bearbeitung.effective_view == PhaseView.form

    def test_department_review_defaults_to_readonly(self):
        flow = TICKET_PHASES[TicketType.zugang_beantragen]
        durch = next(p for p in flow if p.key == "durchfuehrung")
        assert durch.effective_view == PhaseView.readonly
