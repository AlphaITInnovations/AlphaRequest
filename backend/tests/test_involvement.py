"""involved_group_ids / reached_involved_group_ids / involvement_roles."""

from backend.services.workflow_state import (
    involved_group_ids, reached_involved_group_ids, involvement_roles,
)
from backend.tests.factories import make_ticket, wf, phase, group, user, dept


# Ein onboarding-artiger Workflow, in dem alle Phasen erreicht sind.
def onboarding_all_reached(cur=4):
    return wf([
        phase("erstellung", "creation", "done"),
        phase("freigabe", "assignment", "done", responsibility=group("lutz", "Lutz")),
        phase("backoffice", "assignment", "done", responsibility=group("sek", "Sekretariat")),
        phase("bearbeitung", "assignment", "in_progress", responsibility=user("max", "Max")),
        phase("durchfuehrung", "department_review", "in_progress",
              departments={"it": dept("IT"), "hr": dept("HR")}),
    ], idx=cur)


class TestInvolvedGroupIds:
    def test_all_phases_counted(self):
        ids = involved_group_ids(make_ticket(workflow=onboarding_all_reached()))
        assert ids == {"lutz", "sek", "it", "hr"}   # user-Zuständigkeit zählt NICHT

    def test_includes_pending_phases(self):
        t = make_ticket(workflow=wf([
            phase("freigabe", "assignment", "in_progress", responsibility=group("lutz")),
            phase("durchfuehrung", "department_review", "pending", departments={"it": dept("IT")}),
        ], idx=0))
        assert involved_group_ids(t) == {"lutz", "it"}   # auch die pending Durchführung

    def test_old_format_fallback(self):
        t = make_ticket(workflow={"departments": {"it": {}, "hr": {}}})
        assert involved_group_ids(t) == {"it", "hr"}

    def test_empty(self):
        assert involved_group_ids(make_ticket(workflow={})) == set()


class TestReachedInvolvedGroupIds:
    def test_excludes_pending(self):
        t = make_ticket(workflow=wf([
            phase("freigabe", "assignment", "in_progress", responsibility=group("lutz")),
            phase("durchfuehrung", "department_review", "pending", departments={"it": dept("IT")}),
        ], idx=0))
        assert reached_involved_group_ids(t) == {"lutz"}   # it (pending) ausgeschlossen

    def test_all_reached(self):
        assert reached_involved_group_ids(make_ticket(workflow=onboarding_all_reached())) == \
            {"lutz", "sek", "it", "hr"}

    def test_old_format_fallback(self):
        t = make_ticket(workflow={"departments": {"it": {}}})
        assert reached_involved_group_ids(t) == {"it"}


class TestInvolvementRoles:
    def test_creator_only(self):
        t = make_ticket(owner_id="max", workflow={})
        assert involvement_roles(t, "max", set(), set()) == ["ersteller"]

    def test_watcher_only(self):
        t = make_ticket(id=7, owner_id="other", workflow={})
        assert involvement_roles(t, "max", set(), {7}) == ["beobachter"]

    def test_creator_and_watcher(self):
        t = make_ticket(id=7, owner_id="max", workflow={})
        assert involvement_roles(t, "max", set(), {7}) == ["ersteller", "beobachter"]

    def test_onboarding_in_freigabe_it_not_involved_yet(self):
        # REGRESSION: IT-Mitglied darf ein Onboarding-Ticket NICHT sehen, solange es
        # noch in der Freigabe steckt (Durchführung ist pending).
        t = make_ticket(owner_id="other", workflow=wf([
            phase("erstellung", "creation", "done"),
            phase("freigabe", "assignment", "in_progress", responsibility=group("lutz")),
            phase("durchfuehrung", "department_review", "pending", departments={"it": dept("IT")}),
        ], idx=1))
        assert involvement_roles(t, "max", {"it"}, set()) == []

    def test_onboarding_reached_durchfuehrung_it_involved(self):
        t = make_ticket(owner_id="other", workflow=wf([
            phase("erstellung", "creation", "done"),
            phase("freigabe", "assignment", "done", responsibility=group("lutz")),
            phase("durchfuehrung", "department_review", "in_progress", departments={"it": dept("IT")}),
        ], idx=2))
        assert involvement_roles(t, "max", {"it"}, set()) == ["zustaendig", "fachabteilung"]

    def test_responsible_group_member(self):
        t = make_ticket(owner_id="other", workflow=wf([
            phase("freigabe", "assignment", "done", responsibility=group("lutz")),
            phase("backoffice", "assignment", "in_progress", responsibility=group("sek")),
        ], idx=1))
        assert involvement_roles(t, "eva", {"sek"}, set()) == ["zustaendig", "fachabteilung"]

    def test_bearbeiter_via_past_user_responsibility(self):
        t = make_ticket(owner_id="other", workflow=wf([
            phase("bearbeitung", "assignment", "done", responsibility=user("max", "Max")),
            phase("durchfuehrung", "department_review", "in_progress", departments={"it": dept("IT")}),
        ], idx=1))
        assert involvement_roles(t, "max", set(), set()) == ["bearbeiter"]

    def test_bearbeiter_via_history_actor(self):
        t = make_ticket(owner_id="other", workflow={},
                        history=[{"actor": {"id": "max", "type": "user"}, "action": "ticket_updated"}])
        assert involvement_roles(t, "max", set(), set()) == ["bearbeiter"]

    def test_system_actor_is_not_bearbeiter(self):
        t = make_ticket(owner_id="other", workflow={},
                        history=[{"actor": {"id": "max", "type": "system"}, "action": "phase_advanced"}])
        assert involvement_roles(t, "max", set(), set()) == []

    def test_not_involved_at_all(self):
        t = make_ticket(owner_id="other", workflow=onboarding_all_reached(cur=3))
        assert involvement_roles(t, "stranger", {"unrelated-group"}, set()) == []
