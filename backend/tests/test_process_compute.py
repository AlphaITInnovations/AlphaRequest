"""Ebene-1: Wert-Ausdrücke / computed-Felder (services/process_compute)."""


from backend.schemas.process_definition import ProcessDefinition
from backend.services.process_compute import apply_computed


DEFN = ProcessDefinition.model_validate({
    "schemaVersion": 1, "key": "demo", "name": "Demo",
    "fields": [
        {"key": "base.title", "widget": "text"},
        {"key": "sig.title", "widget": "text", "computed": {"from": "base.title"}, "overridable": True},
        {"key": "mirror.title", "widget": "text", "computed": {"from": "base.title"}},  # non-overridable
    ],
    "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                "fields": [{"ref": "base.title"}]}],
})


def test_overridable_fills_when_empty():
    out = apply_computed(DEFN, {"base.title": "Dr."})
    assert out["sig.title"] == "Dr."       # leer → aus Quelle
    assert out["mirror.title"] == "Dr."


def test_overridable_keeps_manual_value():
    out = apply_computed(DEFN, {"base.title": "Dr.", "sig.title": "Prof."})
    assert out["sig.title"] == "Prof."     # manuell gesetzt → bleibt


def test_non_overridable_always_derives():
    out = apply_computed(DEFN, {"base.title": "Dr.", "mirror.title": "Hacked"})
    assert out["mirror.title"] == "Dr."    # non-overridable → immer aus Quelle


def test_empty_source_leaves_overridable_empty():
    out = apply_computed(DEFN, {})
    assert "sig.title" not in out or out.get("sig.title") in (None, "")


def test_computed_map_translates_source_value():
    """Mit `map` wird der Quellwert übersetzt (Position → Fahrzeuggruppe); ein
    nicht enthaltener Wert ergibt einen leeren (None) abgeleiteten Wert."""
    defn = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "position", "widget": "select",
             "options": [{"value": "Disposition"}, {"value": "Werkstudium"}]},
            {"key": "gruppe", "widget": "text",
             "computed": {"from": "position", "map": {"Disposition": "Gruppe 1"}}},
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "position"}]}],
    })
    assert apply_computed(defn, {"position": "Disposition"})["gruppe"] == "Gruppe 1"
    # nicht gemappt → leer (nicht der rohe Quellwert)
    assert apply_computed(defn, {"position": "Werkstudium"}).get("gruppe") is None


def test_computed_from_computed_resolves_regardless_of_order():
    # B leitet aus A ab, A aus base – B steht VOR A deklariert (fixpoint nötig)
    defn = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "b", "widget": "text", "computed": {"from": "a"}},
            {"key": "a", "widget": "text", "computed": {"from": "base"}},
            {"key": "base", "widget": "text"},
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "base"}]}],
    })
    out = apply_computed(defn, {"base": "X"})
    assert out["a"] == "X" and out["b"] == "X"


def test_computed_map_leitet_fahrzeugklasse_aus_position_ab():
    """Regressionsschutz für die Geschäftsregel (früher aus dem Onboarding-Seed):
    ein non-overridable computed-Feld mit `map` leitet die Fahrzeugklasse 1–7 aus
    personal.position ab; Positionen ohne Eintrag in der Map bleiben leer."""
    defn = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "demo", "name": "Demo",
        "fields": [
            {"key": "personal.position", "widget": "text"},
            {"key": "fuhrpark.car_class_number", "widget": "text", "overridable": False,
             "computed": {"from": "personal.position", "map": {
                 "Disposition": "1", "Niederlassungsleitung": "2",
                 "Abteilungsleitung / Verwaltung": "2", "Regionalleitung": "3",
                 "Regionaldirektion": "4", "Geschäftsbereichsleitung": "5",
                 "Geschäftsführung": "6", "C-Level": "7"}}},
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "personal.position"}]}],
    })

    feld = next(f for f in defn.fields if f.key == "fuhrpark.car_class_number")
    assert feld.computed is not None and feld.computed.from_ == "personal.position"
    assert feld.overridable is False        # immer abgeleitet, nicht manuell änderbar

    erwartet = {
        "Disposition": "1",
        "Niederlassungsleitung": "2",
        "Abteilungsleitung / Verwaltung": "2",
        "Regionalleitung": "3",
        "Regionaldirektion": "4",
        "Geschäftsbereichsleitung": "5",
        "Geschäftsführung": "6",
        "C-Level": "7",
    }
    for position, nummer in erwartet.items():
        out = apply_computed(defn, {"personal.position": position})
        assert out["fuhrpark.car_class_number"] == nummer, position

    # Ohne Fahrzeuggruppe (nicht in der Map) → keine Nummer, auch bei manuell gesetztem Wert.
    for ohne in ("Teamassistenz", "Verwaltungsmitarbeitende HQ",
                 "Praktikum / Ausbildung / Werkstudium"):
        out = apply_computed(defn, {"personal.position": ohne,
                                    "fuhrpark.car_class_number": "9"})
        assert out.get("fuhrpark.car_class_number") is None, ohne
