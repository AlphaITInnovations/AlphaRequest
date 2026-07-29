"""Datenübergabe Einstellung (P1) → Onboarding (P2): build_p2_description."""

import copy

from backend.services.onboarding_spawn import build_p2_description


P1_DESC = {
    "base": {
        "salutation": "Frau", "first_name": "Anna", "last_name": "Muster",
        "contract_company": "Alpha", "location": "Berlin",
        "cost_center": "12345", "start_date": "2026-09-01", "title": "Sachbearbeiterin",
    },
    # Gehalt/Konditionen: streng vertraulich, nur in P1 (nur Personalabteilung/Voll-Sicht).
    "personal": {"salary": "50000", "conditions": "13. Gehalt, 30 Tage Urlaub"},
}


def test_transfers_base_and_title_but_not_salary():
    p2 = build_p2_description(P1_DESC, 42)
    assert p2["base"]["first_name"] == "Anna"
    assert p2["base"]["cost_center"] == "12345"
    assert p2["base"]["start_date"] == "2026-09-01"
    # Titel ist ein Basisdatum und wird über base übernommen.
    assert p2["base"]["title"] == "Sachbearbeiterin"
    # Gehalt/Konditionen werden NICHT nach P2 übernommen (Leak-Risiko).
    assert "salary" not in p2["personal"]
    assert "conditions" not in p2["personal"]
    assert p2["_origin_process"] == 42


def test_does_not_carry_it_fuhrpark_fields():
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
