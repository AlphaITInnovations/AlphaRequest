"""Auto-verwaltete Prozesse (seeds/auto): anlegen, unveraendert erkennen, als neue
Version aktualisieren. Ohne DB/Netz – defstore + Gruppen werden gefaked."""
import io
import json

import pytest

from backend.services import seed_definitions as sd


class FakeStore:
    """Minimaler In-Memory-Definitions-Speicher (nur was _ensure_auto_process nutzt)."""

    def __init__(self):
        self.v: dict[str, list[dict]] = {}

    def list_versions(self, key):
        return list(self.v.get(key, []))

    def create_process(self, key, name, definition_json, actor, actor_name):
        self.v[key] = [{"version": 1, "status": "draft",
                        "definition": json.loads(definition_json), "name": name}]

    def publish(self, key, version):
        for r in self.v[key]:
            if r["version"] == version:
                r["status"] = "published"
            elif r["status"] == "published":
                r["status"] = "archived"

    def get_published(self, key):
        return next((r for r in self.v.get(key, []) if r["status"] == "published"), None)

    def create_or_get_draft(self, key, actor, actor_name):
        offen = next((r for r in self.v[key] if r["status"] == "draft"), None)
        if offen:
            return offen
        pub = self.get_published(key)
        nextv = max(r["version"] for r in self.v[key]) + 1
        draft = {"version": nextv, "status": "draft",
                 "definition": dict(pub["definition"]), "name": pub["name"]}
        self.v[key].append(draft)
        return draft

    def update_draft(self, key, version, name, definition_json):
        for r in self.v[key]:
            if r["version"] == version:
                r["definition"] = json.loads(definition_json)
                r["name"] = name


_DEFN = {
    "schemaVersion": 1, "key": "auto-demo", "name": "Auto Demo",
    "fields": [{"key": "base.name", "widget": "text"}],
    "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                "fields": [{"ref": "base.name", "required": True}]}],
}


@pytest.fixture
def auto(tmp_path, monkeypatch):
    pfad = tmp_path / "prozess-auto-demo.json"
    pfad.write_text(json.dumps(_DEFN, ensure_ascii=False), encoding="utf-8")
    store = FakeStore()
    monkeypatch.setattr(sd, "auto_seed_files", lambda: [pfad])
    monkeypatch.setattr(sd, "defstore", store)
    monkeypatch.setattr(sd.groupsdb, "get_groups", lambda: [])
    sd._reset_auto_keys_cache()
    return pfad, store


def test_auto_seed_legt_an_erkennt_unveraendert_und_aktualisiert(auto):
    pfad, store = auto

    # 1) Erstlauf: anlegen + veroeffentlichen (v1).
    r1 = sd.ensure_auto_processes()
    assert [(o.key, o.aktion) for o in r1] == [("auto-demo", "created")]
    assert store.get_published("auto-demo")["version"] == 1

    # 2) Zweiter Lauf ohne Aenderung: nichts tun.
    r2 = sd.ensure_auto_processes()
    assert [o.aktion for o in r2] == ["unchanged"]
    assert store.get_published("auto-demo")["version"] == 1

    # 3) JSON aendern: neue Version, alte bleibt (Tickets pinnen).
    geaendert = dict(_DEFN, name="Auto Demo v2")
    pfad.write_text(json.dumps(geaendert, ensure_ascii=False), encoding="utf-8")
    r3 = sd.ensure_auto_processes()
    assert [o.aktion for o in r3] == ["updated"]
    assert store.get_published("auto-demo")["version"] == 2
    assert store.get_published("auto-demo")["name"] == "Auto Demo v2"
    assert {r["version"] for r in store.list_versions("auto-demo")} == {1, 2}


def test_is_auto_managed(auto):
    assert sd.is_auto_managed("auto-demo") is True
    assert sd.is_auto_managed("zugang-beantragen") is False
    assert sd.is_auto_managed(None) is False


def test_auto_seed_fail_closed_bei_fehlender_gruppe(tmp_path, monkeypatch):
    """Verweist ein Auto-Prozess auf eine Gruppe, die es nicht gibt, wird er NICHT
    eingespielt (Fehler-Outcome), statt einen Platzhalter zu schreiben."""
    defn = dict(_DEFN, key="auto-grp")
    defn["phases"] = [{"key": "start", "kind": "task",
                       "responsibility": {"kind": "group",
                                          "group": "HIER_GRUPPEN_ID_IT_EINSETZEN"},
                       "fields": []}]
    pfad = tmp_path / "prozess-auto-grp.json"
    pfad.write_text(json.dumps(defn, ensure_ascii=False), encoding="utf-8")
    store = FakeStore()
    monkeypatch.setattr(sd, "auto_seed_files", lambda: [pfad])
    monkeypatch.setattr(sd, "defstore", store)
    monkeypatch.setattr(sd.groupsdb, "get_groups", lambda: [])   # keine Gruppen
    sd._reset_auto_keys_cache()

    r = sd.ensure_auto_processes()
    assert r[0].aktion == "error"
    assert store.get_published("auto-grp") is None            # nichts geschrieben
