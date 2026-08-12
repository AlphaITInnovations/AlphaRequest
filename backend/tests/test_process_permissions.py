"""Erstellrechte aus der Prozess-Definition (services/process_permissions)."""

from backend.schemas.process_definition import ProcessDefinition
from backend.services.process_permissions import creatable_keys, may_create


def defn(key="p", **cp):
    return ProcessDefinition.model_validate({
        "key": key, "name": key,
        "createPermissions": cp,
        "fields": [{"key": "a", "widget": "text"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "a"}]}],
    })


ADMIN = {"id": "u_admin", "permissions": ["view", "manage", "admin"]}
USER = {"id": "u1", "permissions": ["view"]}
OTHER = {"id": "u2", "permissions": ["view"]}


def test_default_ist_nur_admin():
    """Ein neuer Prozess darf NICHT versehentlich für alle offen sein."""
    d = defn()
    assert d.createPermissions.everyone is False
    assert d.createPermissions.groups == [] and d.createPermissions.users == []
    assert may_create(d, ADMIN) is True
    assert may_create(d, USER) is False


def test_everyone():
    d = defn(everyone=True)
    assert may_create(d, USER) is True
    assert may_create(d, OTHER) is True


def test_einzelne_person():
    d = defn(users=["u1"])
    assert may_create(d, USER) is True
    assert may_create(d, OTHER) is False


def test_gruppe():
    d = defn(groups=["g_it"])
    assert may_create(d, USER, ["g_it"]) is True
    assert may_create(d, USER, ["g_hr"]) is False
    assert may_create(d, USER, []) is False


def test_admin_umgeht_alles():
    d = defn(everyone=False, groups=["g_x"], users=[])
    assert may_create(d, ADMIN, []) is True


def test_creatable_keys_filtert():
    # Prozess-Schlüssel sind Slugs: Bindestrich, KEIN Unterstrich.
    ds = [defn("offen", everyone=True), defn("nur-it", groups=["g_it"]), defn("zu")]
    assert creatable_keys(ds, USER, ["g_it"]) == {"offen", "nur-it"}
    assert creatable_keys(ds, USER, []) == {"offen"}
    assert creatable_keys(ds, ADMIN, []) == {"offen", "nur-it", "zu"}


def test_rechte_wandern_beim_export_mit():
    """createPermissions ist Teil der Definition – Export/Import nimmt sie mit."""
    d = defn(groups=["g_it"], users=["u1"], everyone=False)
    dumped = d.model_dump(by_alias=True)
    assert dumped["createPermissions"] == {"everyone": False, "groups": ["g_it"], "users": ["u1"]}
    again = ProcessDefinition.model_validate(dumped)
    assert may_create(again, USER, ["g_it"]) is True


def test_alte_definition_ohne_feld_bleibt_gueltig():
    """Bestehende Definitionen (ohne createPermissions) müssen weiter laden."""
    d = ProcessDefinition.model_validate({
        "key": "alt", "name": "Alt",
        "fields": [{"key": "a", "widget": "text"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "a"}]}],
    })
    assert may_create(d, ADMIN) is True
    assert may_create(d, USER) is False
