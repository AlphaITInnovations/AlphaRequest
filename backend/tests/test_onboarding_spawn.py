"""Datenübergabe Einstellung (P1) → Onboarding (P2): build_p2_description."""

import copy

from backend.services.onboarding_spawn import build_p2_description


P1_DESC = {
    "base": {
        "salutation": "Frau", "first_name": "Anna", "last_name": "Muster",
        "contract_company": "Alpha", "location": "Berlin",
        "cost_center": "12345", "start_date": "2026-09-01",
    },
    # Gehalt/Konditionen liegen jetzt im personal-Block (nur Personalabteilung/Voll-Sicht).
    "personal": {"title": "Sachbearbeiterin", "salary": "50000", "conditions": "13. Gehalt, 30 Tage Urlaub"},
}


def test_transfers_base_and_full_personal_and_link():
    p2 = build_p2_description(P1_DESC, 42)
    assert p2["base"]["first_name"] == "Anna"
    assert p2["base"]["cost_center"] == "12345"
    assert p2["base"]["start_date"] == "2026-09-01"
    assert p2["personal"]["title"] == "Sachbearbeiterin"
    assert p2["personal"]["salary"] == "50000"
    assert p2["personal"]["conditions"].startswith("13. Gehalt")
    assert p2["_origin_process"] == 42


def test_does_not_carry_it_fuhrpark_fields():
    # base + personal wandern mit; IT/Fuhrpark bleiben leer (füllt P2).
    p2 = build_p2_description(P1_DESC, 1)
    assert "it" not in p2
    assert "fuhrpark" not in p2
    assert "confidential" not in p2   # aufgelöst → personal


def test_missing_personal_yields_empty_block():
    p2 = build_p2_description({"base": {"first_name": "X"}}, 1)
    assert p2["personal"] == {}


def test_input_not_mutated():
    original = copy.deepcopy(P1_DESC)
    build_p2_description(P1_DESC, 7)
    assert P1_DESC == original


def test_non_dict_input_is_safe():
    p2 = build_p2_description(None, 5)
    assert p2["base"] == {} and p2["personal"] == {} and p2["_origin_process"] == 5
