"""Migration der Onboarding-Beschreibung ins neue base-Format
(backend/services/onboarding_migration.py)."""

from backend.services.onboarding_migration import migrate_onboarding_desc


# Alt-Format: Basisdaten unter personal, private_address statt private_street,
# Signatur-Firma unter allgemein.
DESC_LEGACY = {
    "personal": {
        "first_name": "Old", "last_name": "Legacy", "contract_company": "Alpha",
        "location": "Berlin", "cost_center": "CC-9", "start_date": "2026-08-01",
        "title": "Leiter", "personal_number": "999",
        "private_address": "Musterweg 1",
    },
    "allgemein": {"appearance_company": "Alpha GmbH"},
    "it": {"software": {"datev": True}},
    "fuhrpark": {"car": "Ja"},
}

# Neues Format: eigener base-Block (inkl. Titel), personal nur HR-Felder.
DESC_NEW = {
    "base": {
        "salutation": "Frau", "first_name": "Anna", "last_name": "Muster",
        "contract_company": "Alpha", "location": "Berlin", "cost_center": "CC-1",
        "start_date": "2026-01-01", "title": "Leiterin",
    },
    "personal": {
        "personal_number": "12345", "private_street": "Weg 1", "department": "IT",
    },
    "it": {"appearance_company": "Alpha", "software": {"datev": True}},
    "fuhrpark": {"car": "Ja"},
}


def test_legacy_desc_is_migrated_to_base_format():
    out = migrate_onboarding_desc(DESC_LEGACY)

    # Basisfelder sind jetzt in base …
    assert out["base"]["first_name"] == "Old"
    assert out["base"]["last_name"] == "Legacy"
    assert out["base"]["contract_company"] == "Alpha"
    assert out["base"]["location"] == "Berlin"
    assert out["base"]["cost_center"] == "CC-9"
    assert out["base"]["start_date"] == "2026-08-01"
    assert out["base"]["title"] == "Leiter"   # Berufsbezeichnung ist Basisdatum
    # Anrede gab es im Alt-Format nicht → leer.
    assert out["base"]["salutation"] == ""

    # … und aus personal entfernt; HR-Felder bleiben.
    for k in ("first_name", "last_name", "contract_company", "location", "cost_center", "start_date", "title"):
        assert k not in out["personal"]
    assert out["personal"]["personal_number"] == "999"

    # private_address → private_street; alter Schlüssel weg.
    assert out["personal"]["private_street"] == "Musterweg 1"
    assert "private_address" not in out["personal"]

    # allgemein.appearance_company → it.appearance_company; allgemein entfernt.
    assert out["it"]["appearance_company"] == "Alpha GmbH"
    assert out["it"]["software"]["datev"] is True
    assert "allgemein" not in out

    assert out["fuhrpark"]["car"] == "Ja"


def test_new_format_is_unchanged():
    out = migrate_onboarding_desc(DESC_NEW)
    assert out == DESC_NEW


def test_migration_is_idempotent():
    once = migrate_onboarding_desc(DESC_LEGACY)
    twice = migrate_onboarding_desc(once)
    assert once == twice


def test_does_not_overwrite_existing_base_values():
    desc = {
        "base": {"first_name": "Neu"},
        "personal": {"first_name": "Alt", "last_name": "Nachname"},
    }
    out = migrate_onboarding_desc(desc)
    # base gewinnt, wird nicht durch personal überschrieben …
    assert out["base"]["first_name"] == "Neu"
    # … fehlender Nachname wird aber aus personal nachgezogen.
    assert out["base"]["last_name"] == "Nachname"
    assert "first_name" not in out["personal"]
    assert "last_name" not in out["personal"]


def test_does_not_overwrite_existing_appearance_company():
    desc = {
        "allgemein": {"appearance_company": "Alt GmbH"},
        "it": {"appearance_company": "Neu GmbH"},
    }
    out = migrate_onboarding_desc(desc)
    assert out["it"]["appearance_company"] == "Neu GmbH"
    assert "allgemein" not in out


def test_input_is_not_mutated():
    import copy
    original = copy.deepcopy(DESC_LEGACY)
    migrate_onboarding_desc(DESC_LEGACY)
    assert DESC_LEGACY == original


def test_non_dict_passthrough():
    assert migrate_onboarding_desc(None) is None
    assert migrate_onboarding_desc("x") == "x"
