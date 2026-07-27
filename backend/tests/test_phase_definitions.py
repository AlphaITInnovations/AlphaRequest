"""Sichert die Workflow-Definitionen (Keys, Reihenfolge, Typen, assign_groups)."""

from backend.services.phase_definitions import TICKET_PHASES, PhaseType, PhaseView
from backend.models.models import TicketType


class TestEinstellungFlow:
    """Onboarding Prozess 1 – Einstellung Mitarbeiter:in."""

    def setup_method(self):
        self.flow = TICKET_PHASES[TicketType.einstellung]

    def test_phase_keys_and_order(self):
        assert [p.key for p in self.flow] == [
            "erstellung", "freigabe", "vertrag", "vertragsruecklauf",
        ]

    def test_phase_types(self):
        assert [p.type for p in self.flow] == [
            PhaseType.creation, PhaseType.assignment,
            PhaseType.assignment, PhaseType.assignment,
        ]

    def test_assign_groups(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["freigabe"].assign_group == "FreigabeHerrLutz"
        assert by_key["vertrag"].assign_group == "Sekretariat GL"
        assert by_key["vertragsruecklauf"].assign_group == "Sekretariat GL"

    def test_freigabe_is_approval_view(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["freigabe"].effective_view == PhaseView.approval

    def test_vertragsruecklauf_enters_waiting_status(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["vertragsruecklauf"].enter_status == "waiting_contract"
        # Alle anderen Phasen nutzen die Standard-Statuslogik.
        assert all(p.enter_status is None for p in self.flow if p.key != "vertragsruecklauf")


class TestOnboardingP2Flow:
    """Onboarding Prozess 2 – nach Vertragsrücklauf (zugang-beantragen)."""

    def setup_method(self):
        self.flow = TICKET_PHASES[TicketType.zugang_beantragen]

    def test_phase_keys_and_order(self):
        assert [p.key for p in self.flow] == [
            "erstellung", "bearbeitung_sgl", "bearbeitung", "durchfuehrung",
        ]

    def test_phase_types(self):
        assert [p.type for p in self.flow] == [
            PhaseType.creation, PhaseType.assignment,
            PhaseType.assignment, PhaseType.department_review,
        ]

    def test_assign_groups(self):
        by_key = {p.key: p for p in self.flow}
        assert by_key["bearbeitung_sgl"].assign_group == "Sekretariat GL"
        assert by_key["bearbeitung"].assign_group is None   # freie Bearbeiterwahl (Vorgesetzte:r)

    def test_no_freigabe_phase(self):
        # Die Freigabe (Lutz) sitzt jetzt in Prozess 1, nicht mehr in P2.
        assert "freigabe" not in [p.key for p in self.flow]


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
