"""Datenübergabe Einstellung (P1) → Onboarding (P2): build_p2_description."""

import copy

from backend.services.onboarding_spawn import build_p2_description


P1_DESC = {
    "base": {
        "salutation": "Frau", "first_name": "Anna", "last_name": "Muster",
        "contract_company": "Alpha", "location": "Berlin",
        "cost_center": "12345", "start_date": "2026-09-01",
    },
    "personal": {"title": "Sachbearbeiterin"},
    "confidential": {"salary": "50000", "conditions": "13. Gehalt, 30 Tage Urlaub"},
    "_creator": {"id": "vg-1", "name": "Chef:in"},
}


def test_transfers_base_title_confidential_and_link():
    p2 = build_p2_description(P1_DESC, 42)
    assert p2["base"]["first_name"] == "Anna"
    assert p2["base"]["cost_center"] == "12345"
    assert p2["base"]["start_date"] == "2026-09-01"
    assert p2["personal"]["title"] == "Sachbearbeiterin"
    assert p2["confidential"]["salary"] == "50000"
    assert p2["confidential"]["conditions"].startswith("13. Gehalt")
    assert p2["_origin_process"] == 42


def test_does_not_carry_hr_it_fuhrpark_fields():
    # Nur base/title/confidential wandern mit; der Rest bleibt leer (füllt P2).
    p2 = build_p2_description(P1_DESC, 1)
    assert set(p2["personal"].keys()) == {"title"}
    assert "it" not in p2
    assert "fuhrpark" not in p2


def test_missing_confidential_yields_empty_block():
    p2 = build_p2_description({"base": {"first_name": "X"}}, 1)
    assert p2["confidential"] == {}
    assert p2["personal"] == {}   # kein Titel vorhanden


def test_empty_title_not_carried():
    p2 = build_p2_description({"base": {}, "personal": {"title": ""}}, 1)
    assert p2["personal"] == {}


def test_input_not_mutated():
    original = copy.deepcopy(P1_DESC)
    build_p2_description(P1_DESC, 7)
    assert P1_DESC == original


def test_non_dict_input_is_safe():
    p2 = build_p2_description(None, 5)
    assert p2["base"] == {} and p2["confidential"] == {} and p2["_origin_process"] == 5
