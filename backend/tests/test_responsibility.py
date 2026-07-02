"""current_responsibility / primary_responsibility / responsibility_label / user_is_responsible."""

from backend.services.workflow_state import (
    current_responsibility, primary_responsibility, responsibility_label,
    user_is_responsible,
)
from backend.tests.factories import make_ticket, wf, phase, group, user, dept


class TestCurrentResponsibility:
    def test_empty_workflow_is_none(self):
        assert current_responsibility(make_ticket(workflow={})) == {"kind": "none"}

    def test_old_format_without_phases_is_none(self):
        t = make_ticket(workflow={"departments": {"it": {}}})
        assert current_responsibility(t) == {"kind": "none"}

    def test_creation_phase_falls_back_to_owner(self):
        t = make_ticket(owner_id="o1", owner_name="Chef",
                        workflow=wf([phase("erstellung", "creation")], idx=0))
        assert current_responsibility(t) == {"kind": "owner", "id": "o1", "name": "Chef"}

    def test_assignment_with_group_responsibility(self):
        t = make_ticket(workflow=wf([phase("backoffice", "assignment",
                                            responsibility=group("g1", "Sekretariat"))], idx=0))
        assert current_responsibility(t) == {"kind": "group", "id": "g1", "name": "Sekretariat"}

    def test_assignment_without_responsibility_is_none(self):
        t = make_ticket(workflow=wf([phase("bearbeitung", "assignment")], idx=0))
        assert current_responsibility(t) == {"kind": "none"}

    def test_department_review_returns_departments(self):
        depts = {"it": dept("IT"), "hr": dept("HR", status="done")}
        t = make_ticket(workflow=wf([phase("durchfuehrung", "department_review", departments=depts)], idx=0))
        resp = current_responsibility(t)
        assert resp["kind"] == "departments"
        assert resp["departments"] == depts

    def test_index_out_of_range_is_none(self):
        t = make_ticket(workflow=wf([phase("a", "assignment", responsibility=group("g"))], idx=5))
        assert current_responsibility(t) == {"kind": "none"}


class TestPrimaryResponsibility:
    def test_group_returns_kind_id_name(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=group("g1", "IT"))]))
        assert primary_responsibility(t) == {"kind": "group", "id": "g1", "name": "IT"}

    def test_user_returns_kind_id_name(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=user("u1", "Max"))]))
        assert primary_responsibility(t) == {"kind": "user", "id": "u1", "name": "Max"}

    def test_owner_returns_none(self):
        t = make_ticket(workflow=wf([phase("erstellung", "creation")]))
        assert primary_responsibility(t) is None

    def test_departments_returns_none(self):
        t = make_ticket(workflow=wf([phase("d", "department_review", departments={"it": dept("IT")})]))
        assert primary_responsibility(t) is None

    def test_empty_returns_none(self):
        assert primary_responsibility(make_ticket(workflow={})) is None


class TestResponsibilityLabel:
    def test_user_name(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=user("u", "Max Mustermann"))]))
        assert responsibility_label(t) == "Max Mustermann"

    def test_group_name(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=group("g", "IT"))]))
        assert responsibility_label(t) == "IT"

    def test_owner_name(self):
        t = make_ticket(owner_name="Chefin", workflow=wf([phase("e", "creation")]))
        assert responsibility_label(t) == "Chefin"

    def test_departments_only_open_required(self):
        depts = {
            "it": dept("IT", required=True, status="open"),
            "hr": dept("HR", required=True, status="done"),      # erledigt → raus
            "opt": dept("Optional", required=False, status="open"),  # nicht Pflicht → raus
        }
        t = make_ticket(workflow=wf([phase("d", "department_review", departments=depts)]))
        assert responsibility_label(t) == "IT"

    def test_departments_multiple_open(self):
        depts = {"it": dept("IT"), "fp": dept("Fuhrpark")}
        t = make_ticket(workflow=wf([phase("d", "department_review", departments=depts)]))
        # Reihenfolge = Einfügereihenfolge des Dicts
        assert responsibility_label(t) == "IT, Fuhrpark"

    def test_none_is_dash(self):
        assert responsibility_label(make_ticket(workflow={})) == "—"

    def test_group_without_name_is_dash(self):
        t = make_ticket(workflow=wf([phase("p", "assignment",
                                            responsibility={"kind": "group", "id": "g", "name": None})]))
        assert responsibility_label(t) == "—"


class TestUserIsResponsible:
    def test_user_match(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=user("max", "Max"))]))
        assert user_is_responsible(t, "max") is True
        assert user_is_responsible(t, "eva") is False

    def test_group_membership(self):
        t = make_ticket(workflow=wf([phase("p", "assignment", responsibility=group("g1", "IT"))]))
        assert user_is_responsible(t, "x", {"g1"}) is True
        assert user_is_responsible(t, "x", {"g2"}) is False
        assert user_is_responsible(t, "x") is False  # keine Gruppen übergeben

    def test_owner(self):
        t = make_ticket(owner_id="max", workflow=wf([phase("e", "creation")]))
        assert user_is_responsible(t, "max") is True
        assert user_is_responsible(t, "eva") is False

    def test_departments_open_required_member(self):
        depts = {"it": dept("IT", status="open"), "hr": dept("HR", status="done")}
        t = make_ticket(workflow=wf([phase("d", "department_review", departments=depts)]))
        assert user_is_responsible(t, "x", {"it"}) is True     # offene Pflicht-Abteilung
        assert user_is_responsible(t, "x", {"hr"}) is False    # bereits erledigt
        assert user_is_responsible(t, "x", {"other"}) is False

    def test_departments_not_required_is_false(self):
        depts = {"opt": dept("Optional", required=False, status="open")}
        t = make_ticket(workflow=wf([phase("d", "department_review", departments=depts)]))
        assert user_is_responsible(t, "x", {"opt"}) is False
