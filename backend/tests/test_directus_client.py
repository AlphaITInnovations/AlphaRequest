"""Ebene-1: Directus-Lese-Client (services/directus_client) – ohne echtes Netz.

HTTP wird über eine `requests`-Attrappe geprüft (URL/Header/Params, Fehler-
Mapping), die reine Parsing-/Mapping-Logik über ein gemocktes `_request`.
"""
import json

import pytest
import requests as real_requests

from backend.services import directus_client as dc


class FakeResp:
    def __init__(self, status=200, json_data=None, text="", raise_json=False):
        self.status_code = status
        self._json = json_data
        self.text = text
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("kein JSON")
        return self._json


class FakeRequests:
    RequestException = real_requests.RequestException

    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None, verify=None):
        self.calls.append({"url": url, "headers": headers, "params": params,
                           "timeout": timeout, "verify": verify})
        if self.exc:
            raise self.exc
        return self.resp


class FakeWriteRequests:
    RequestException = real_requests.RequestException

    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None, verify=None):
        self.calls.append({"method": method, "url": url, "json": json, "verify": verify})
        return self.resp


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(dc.config, "DIRECTUS_URL", "https://directus.test")
    monkeypatch.setattr(dc.config, "DIRECTUS_TOKEN", "tok")
    monkeypatch.setattr(dc.config, "DIRECTUS_TIMEOUT", 7)


def test_is_configured(monkeypatch):
    monkeypatch.setattr(dc.config, "DIRECTUS_URL", "")
    monkeypatch.setattr(dc.config, "DIRECTUS_TOKEN", "")
    assert dc.is_configured() is False
    monkeypatch.setattr(dc.config, "DIRECTUS_URL", "https://x")
    monkeypatch.setattr(dc.config, "DIRECTUS_TOKEN", "t")
    assert dc.is_configured() is True


def test_request_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(dc.config, "DIRECTUS_URL", "")
    monkeypatch.setattr(dc.config, "DIRECTUS_TOKEN", "")
    with pytest.raises(dc.DirectusError):
        dc._request("/items/x")


def test_request_builds_url_headers_params_and_unpacks(configured, monkeypatch):
    fake = FakeRequests(FakeResp(200, {"data": [{"a": 1}]}))
    monkeypatch.setattr(dc, "requests", fake)
    out = dc._request("/items/kostenstellen", params={"limit": 5})
    assert out == [{"a": 1}]
    call = fake.calls[0]
    assert call["url"] == "https://directus.test/items/kostenstellen"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["params"] == {"limit": 5}
    assert call["timeout"] == 7


def test_verify_resolution(monkeypatch):
    # CA-Bundle gewinnt (prüft weiter gegen die Datei) …
    monkeypatch.setattr(dc.config, "DIRECTUS_CA_BUNDLE", "/etc/ssl/directus-ca.pem")
    monkeypatch.setattr(dc.config, "DIRECTUS_VERIFY_SSL", False)
    assert dc._verify() == "/etc/ssl/directus-ca.pem"
    # … ohne Bundle steuert das Flag: False = Prüfung aus (self-signed), sonst True.
    monkeypatch.setattr(dc.config, "DIRECTUS_CA_BUNDLE", "")
    monkeypatch.setattr(dc.config, "DIRECTUS_VERIFY_SSL", False)
    assert dc._verify() is False
    monkeypatch.setattr(dc.config, "DIRECTUS_VERIFY_SSL", True)
    assert dc._verify() is True


def test_request_passes_verify(configured, monkeypatch):
    monkeypatch.setattr(dc.config, "DIRECTUS_VERIFY_SSL", False)
    monkeypatch.setattr(dc.config, "DIRECTUS_CA_BUNDLE", "")
    fake = FakeRequests(FakeResp(200, {"data": []}))
    monkeypatch.setattr(dc, "requests", fake)
    dc._request("/items/x")
    assert fake.calls[0]["verify"] is False


def test_request_http_error_maps_message_and_status(configured, monkeypatch):
    fake = FakeRequests(FakeResp(403, {"errors": [{"message": "Forbidden"}]}))
    monkeypatch.setattr(dc, "requests", fake)
    with pytest.raises(dc.DirectusError) as ei:
        dc._request("/items/x")
    assert ei.value.status == 403
    assert "Forbidden" in str(ei.value)


def test_request_network_error_maps(configured, monkeypatch):
    fake = FakeRequests(exc=real_requests.ConnectionError("boom"))
    monkeypatch.setattr(dc, "requests", fake)
    with pytest.raises(dc.DirectusError) as ei:
        dc._request("/x")
    assert "nicht erreichbar" in str(ei.value)


def test_request_non_json_raises(configured, monkeypatch):
    fake = FakeRequests(FakeResp(200, None, text="<html>", raise_json=True))
    monkeypatch.setattr(dc, "requests", fake)
    with pytest.raises(dc.DirectusError):
        dc._request("/x")


def test_list_collections_filters_only_system(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: [
        {"collection": "directus_users", "schema": {}, "meta": {}},
        {"collection": "ordner", "schema": None, "meta": {}},
        {"collection": "kostenstellen", "schema": {"name": "kostenstellen"},
         "meta": {"note": "KST", "icon": "tag", "hidden": False}},
    ])
    cols = dc.list_collections()
    # Nur System (directus_*) wird gefiltert; schema-None (z. B. Ordner) bleibt jetzt
    # drin, damit eingeschränkte Tokens ihre echten Collections sehen.
    assert [c["collection"] for c in cols] == ["kostenstellen", "ordner"]
    assert next(c for c in cols if c["collection"] == "kostenstellen")["note"] == "KST"


def test_list_fields_maps_type_and_relation(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: [
        {"field": "id", "type": "integer", "schema": {"is_primary_key": True}, "meta": {}},
        {"field": "firma", "type": "integer",
         "schema": {"foreign_key_table": "firmen"}, "meta": {"note": "FK"}},
        {"field": None},
    ])
    fs = dc.list_fields("kostenstellen")
    assert {f["field"] for f in fs} == {"id", "firma"}
    assert next(f for f in fs if f["field"] == "id")["primaryKey"] is True
    assert next(f for f in fs if f["field"] == "firma")["relatedCollection"] == "firmen"


def test_query_items_builds_params(configured, monkeypatch):
    seen = {}

    def fake_req(path, params=None):
        seen["path"] = path
        seen["params"] = params
        return [{"nummer": "1"}]

    monkeypatch.setattr(dc, "_request", fake_req)
    out = dc.query_items("kostenstellen", fields=["nummer", "firma.name"],
                         filter={"aktiv": {"_eq": True}}, sort=["nummer"], limit=20, search="10")
    assert out == [{"nummer": "1"}]
    assert seen["path"] == "/items/kostenstellen"
    p = seen["params"]
    assert p["fields"] == "nummer,firma.name"
    assert p["sort"] == "nummer"
    assert p["search"] == "10"
    assert p["limit"] == 20
    assert json.loads(p["filter"]) == {"aktiv": {"_eq": True}}


def test_sample_fields_from_item(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: [{"nummer": "1", "firma": 5}])
    assert {f["field"] for f in dc.sample_fields("kst")} == {"nummer", "firma"}


def test_sample_fields_empty(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: [])
    assert dc.sample_fields("kst") == []


def test_query_items_non_list_data_is_empty(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: None)
    assert dc.query_items("x") == []


def test_create_item_posts_and_unpacks(configured, monkeypatch):
    fake = FakeWriteRequests(FakeResp(200, {"data": {"id": 7, "name": "Max"}}))
    monkeypatch.setattr(dc, "requests", fake)
    out = dc.create_item("mitarbeiter", {"name": "Max"})
    assert out == {"id": 7, "name": "Max"}
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["url"].endswith("/items/mitarbeiter")
    assert fake.calls[0]["json"] == {"name": "Max"}


def test_update_item_patches(configured, monkeypatch):
    fake = FakeWriteRequests(FakeResp(200, {"data": {"id": 7}}))
    monkeypatch.setattr(dc, "requests", fake)
    dc.update_item("mitarbeiter", 7, {"name": "Neu"})
    assert fake.calls[0]["method"] == "PATCH"
    assert fake.calls[0]["url"].endswith("/items/mitarbeiter/7")


def test_delete_item_handles_204(configured, monkeypatch):
    fake = FakeWriteRequests(FakeResp(204, None))
    monkeypatch.setattr(dc, "requests", fake)
    dc.delete_item("mitarbeiter", 7)
    assert fake.calls[0]["method"] == "DELETE"


def test_write_http_error_maps(configured, monkeypatch):
    fake = FakeWriteRequests(FakeResp(403, {"errors": [{"message": "Forbidden"}]}))
    monkeypatch.setattr(dc, "requests", fake)
    with pytest.raises(dc.DirectusError):
        dc.create_item("x", {})


def test_write_encodes_path_segments(configured, monkeypatch):
    # Eine item_id aus einem Nutzerfeld darf das Request-Ziel nicht verbiegen.
    fake = FakeWriteRequests(FakeResp(204, None))
    monkeypatch.setattr(dc, "requests", fake)
    dc.delete_item("mitarbeiter", "1/../users")
    assert fake.calls[0]["url"].endswith("/items/mitarbeiter/1%2F..%2Fusers")


def test_status_unconfigured(monkeypatch):
    monkeypatch.setattr(dc.config, "DIRECTUS_URL", "")
    monkeypatch.setattr(dc.config, "DIRECTUS_TOKEN", "")
    assert dc.status() == {"configured": False, "ok": False, "error": None}


def test_status_ok_and_error(configured, monkeypatch):
    monkeypatch.setattr(dc, "_request", lambda path, params=None: {"project_name": "x"})
    assert dc.status()["ok"] is True

    def boom(path, params=None):
        raise dc.DirectusError("down", status=502)

    monkeypatch.setattr(dc, "_request", boom)
    st = dc.status()
    assert st["configured"] is True and st["ok"] is False and "down" in st["error"]
