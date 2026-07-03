"""Unit-Tests für die reine Admin-Gruppen-Sync-Entscheidung (ohne DB)."""

from backend.services.admin_sync import (
    decide_group_admin_action, ACTION_PROMOTE, ACTION_REVOKE,
)


def _decide(**kw):
    base = dict(
        admin_group_configured=True,
        groups_authoritative=True,
        is_in_admin_group=False,
        current_role="none",
        admin_via_group=False,
    )
    base.update(kw)
    return decide_group_admin_action(**base)


# ── Gate: nur aktiv bei konfigurierter Gruppe + verlässlichem Claim ──────────────

def test_keine_gruppe_konfiguriert_macht_nichts():
    assert _decide(admin_group_configured=False, is_in_admin_group=True) is None


def test_overage_claim_macht_nichts():
    # groups_authoritative=False → Mitgliedschaft unbekannt → nichts anfassen,
    # selbst wenn der User Admin ist.
    assert _decide(groups_authoritative=False, current_role="admin",
                   admin_via_group=True) is None


# ── In der Gruppe: befördern / adoptieren ───────────────────────────────────────

def test_in_gruppe_nicht_admin_wird_befoerdert():
    assert _decide(is_in_admin_group=True, current_role="none") == ACTION_PROMOTE


def test_in_gruppe_manuell_admin_wird_adoptiert():
    # Manuell gesetzter Admin (Flag=0), der in der Gruppe ist → als gruppen-basiert
    # markieren (PROMOTE setzt Flag=1).
    assert _decide(is_in_admin_group=True, current_role="admin",
                   admin_via_group=False) == ACTION_PROMOTE


def test_in_gruppe_bereits_gruppenadmin_macht_nichts():
    assert _decide(is_in_admin_group=True, current_role="admin",
                   admin_via_group=True) is None


def test_in_gruppe_manager_wird_zu_admin():
    assert _decide(is_in_admin_group=True, current_role="manager") == ACTION_PROMOTE


# ── Nicht in der Gruppe: nur gruppen-basierte Admins entziehen ───────────────────

def test_nicht_in_gruppe_gruppenadmin_wird_entzogen():
    assert _decide(is_in_admin_group=False, current_role="admin",
                   admin_via_group=True) == ACTION_REVOKE


def test_nicht_in_gruppe_manueller_admin_bleibt():
    # KERNANFORDERUNG: ein manuell vergebener Admin ausserhalb der Gruppe
    # darf NICHT automatisch entzogen werden.
    assert _decide(is_in_admin_group=False, current_role="admin",
                   admin_via_group=False) is None


def test_nicht_in_gruppe_manager_bleibt():
    assert _decide(is_in_admin_group=False, current_role="manager",
                   admin_via_group=False) is None


def test_nicht_in_gruppe_ohne_rolle_macht_nichts():
    assert _decide(is_in_admin_group=False, current_role="none") is None
