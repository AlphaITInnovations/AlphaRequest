"""Phasen-Hilfsfunktionen: Formaterkennung, aktuelle Phase, Ansicht."""

from backend.services.workflow_state import _is_new_format, _current_phase_of, phase_view
from backend.tests.factories import wf, phase


class TestIsNewFormat:
    def test_with_phases(self):
        assert _is_new_format({"phases": []}) is True

    def test_empty(self):
        assert _is_new_format({}) is False

    def test_old_format(self):
        assert _is_new_format({"departments": {}}) is False


class TestCurrentPhaseOf:
    def test_returns_active_phase(self):
        a, b = phase("a", "assignment"), phase("b", "department_review")
        assert _current_phase_of(wf([a, b], idx=1)) is b

    def test_first_phase(self):
        a = phase("a", "creation")
        assert _current_phase_of(wf([a], idx=0)) is a

    def test_index_out_of_range(self):
        assert _current_phase_of(wf([phase("a", "assignment")], idx=5)) is None

    def test_old_format_none(self):
        assert _current_phase_of({}) is None
        assert _current_phase_of({"departments": {}}) is None


class TestPhaseView:
    def test_none_is_readonly(self):
        assert phase_view(None) == "readonly"

    def test_explicit_form(self):
        assert phase_view({"view": "form", "type": "department_review"}) == "form"

    def test_explicit_readonly(self):
        assert phase_view({"view": "readonly", "type": "assignment"}) == "readonly"

    def test_assignment_defaults_to_form(self):
        assert phase_view({"type": "assignment"}) == "form"

    def test_department_review_defaults_to_readonly(self):
        assert phase_view({"type": "department_review"}) == "readonly"

    def test_creation_defaults_to_readonly(self):
        assert phase_view({"type": "creation"}) == "readonly"
