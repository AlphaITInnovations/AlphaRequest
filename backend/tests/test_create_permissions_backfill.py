"""Ebene-1: Abbildung der Alt-Erstellrechte auf `createPermissions` (DB-frei).

Geprüft wird die reine Funktion mit Beispiel-Altdaten – kein DB-Zugriff, keine
echten Gruppen.
"""

from backend.services.create_permissions_backfill import (
    EVERYONE_SENTINEL,
    LEGACY_TYPE_TO_PROCESS_KEY,
    build_create_permissions,
    merge_into_definition,
)

# Zwei interne Fachabteilungen (die wirken) …
FACH_IT = "fach-it-0001"
FACH_HR = "fach-hr-0002"
# … und eine Azure-AD-Gruppe (die `may_create` nie zu sehen bekommt).
AD_GUID = "8f1e2c34-5b6a-47d8-9e0f-112233445566"


def test_sentinel_wird_zu_everyone():
    res = build_create_permissions(
        {}, {"basis-ticket": [EVERYONE_SENTINEL]}, department_group_ids={FACH_IT})
    assert res.permissions["basis-ticket"]["everyone"] is True
    assert res.permissions["basis-ticket"]["groups"] == []


def test_nutzerrechte_wandern_nach_users():
    res = build_create_permissions(
        {"hardware": ["u-2", "u-1", "u-1"]}, {}, department_group_ids=set())
    assert res.permissions["hardware"]["users"] == ["u-1", "u-2"]
    assert res.permissions["hardware"]["everyone"] is False


def test_fachabteilungen_wirken_ad_gruppen_nicht():
    res = build_create_permissions(
        {}, {"zugang-beantragen": [FACH_IT, AD_GUID, FACH_HR]},
        department_group_ids={FACH_IT, FACH_HR})
    perms = res.permissions["zugang-beantragen"]
    assert perms["groups"] == sorted([FACH_IT, FACH_HR])
    # Nicht stillschweigend mitgeschrieben, sondern gemeldet.
    assert AD_GUID not in perms["groups"]
    assert res.ineffective_groups["zugang-beantragen"] == [AD_GUID]


def test_unbekannter_tickettyp_wird_gemeldet_nicht_geraten():
    res = build_create_permissions(
        {"gibtsnichtmehr": ["u-1"]}, {}, department_group_ids=set())
    assert res.unmapped_types == ["gibtsnichtmehr"]
    assert "gibtsnichtmehr" not in res.permissions


def test_leerer_tickettyp_erzeugt_leere_rechte_keine_meldung():
    res = build_create_permissions({"hardware": []}, {"hardware": []}, department_group_ids=set())
    assert res.permissions["hardware"] == {"everyone": False, "groups": [], "users": []}
    assert res.unmapped_types == []
    assert res.ineffective_groups == {}


# Die Tickettypen des Alt-Systems (früher `models.models.TicketType`). Hier als
# Literal festgeschrieben, weil das Enum mit dem Alt-System entfallen ist – die
# Abbildung muss die Liste trotzdem vollständig abdecken, sonst verliert ein
# Kunde beim Cutover still die Erstellrechte eines Typs.
ALT_TICKETTYPEN = {
    "hardware", "niederlassung-anmelden", "niederlassung-schliessen",
    "niederlassung-umzug", "einstellung", "zugang-beantragen", "zugang-sperren",
    "marketing-stellenanzeige", "hotelbuchung", "basis-ticket",
}


def test_abbildung_deckt_alle_alt_tickettypen_ab():
    """Explizite Abbildung – kein Typ darf beim Cutover unbemerkt wegfallen."""
    assert set(LEGACY_TYPE_TO_PROCESS_KEY) == ALT_TICKETTYPEN


def test_sentinel_stimmt_mit_alt_system_ueberein():
    """Der Wert steht so in den Alt-Zeilen von `ticket_group_permissions` – er ist
    Datenformat, nicht Geschmackssache, und darf sich nicht ändern."""
    assert EVERYONE_SENTINEL == "__everyone__"


def test_merge_nimmt_dem_seed_nichts_weg():
    seed = {"key": "basis-ticket",
            "createPermissions": {"everyone": True, "groups": ["g-alt"], "users": []}}
    merged = merge_into_definition(seed, {"everyone": False, "groups": [FACH_IT], "users": ["u-1"]})
    assert merged["createPermissions"] == {
        "everyone": True, "groups": sorted([FACH_IT, "g-alt"]), "users": ["u-1"]}
    # Original unangetastet
    assert seed["createPermissions"]["groups"] == ["g-alt"]


def test_merge_ergaenzt_fehlenden_block():
    """prozess-hotelbuchung.json liefert gar keinen createPermissions-Block."""
    merged = merge_into_definition({"key": "hotelbuchung"},
                                   {"everyone": False, "groups": [FACH_IT], "users": []})
    assert merged["createPermissions"] == {"everyone": False, "groups": [FACH_IT], "users": []}


def test_merge_ohne_altdaten_laesst_seed_stehen():
    merged = merge_into_definition({"createPermissions": {"everyone": True}}, None)
    assert merged["createPermissions"] == {"everyone": True, "groups": [], "users": []}
