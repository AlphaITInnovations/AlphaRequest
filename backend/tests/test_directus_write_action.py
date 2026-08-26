"""Ebene-1: Automations-Aktion directus_write (services/directus_write_action) – ohne Netz."""
import pytest

from backend.schemas.process_definition import (
    Action, DirectusOperation, DirectusWriteBinding, DirectusWriteSpec,
)
from backend.services import directus_client as dc
from backend.services import directus_write_action as dwa


class FakeClient:
    DirectusError = dc.DirectusError

    def __init__(self, created=None, exc=None, existing_id=None):
        self.created = created if created is not None else {"id": 99}
        self.exc = exc
        self.existing_id = existing_id
        self.calls = []

    def find_one_id(self, collection, field, value):
        self.calls.append(("find", collection, field, value))
        return self.existing_id

    def create_item(self, collection, payload):
        self.calls.append(("create", collection, payload))
        if self.exc:
            raise self.exc
        return self.created

    def update_item(self, collection, item_id, payload):
        self.calls.append(("update", collection, item_id, payload))
        if self.exc:
            raise self.exc
        return {"id": item_id}

    def delete_item(self, collection, item_id):
        self.calls.append(("delete", collection, item_id))
        if self.exc:
            raise self.exc


def _action(op, field_map, id_field="mitarbeiter.directus_id", on_error=None, match_field=None):
    kw = dict(operation=op, collection="mitarbeiter",
              fieldMap=[DirectusWriteBinding(source=s, target=t) for s, t in field_map],
              idField=id_field)
    if on_error:
        kw["onError"] = on_error
    if match_field:
        kw["matchField"] = match_field
    return Action(type="directus_write", directus=DirectusWriteSpec(**kw))


NOOP = lambda *a, **k: None  # noqa: E731


def test_build_payload_skips_empty():
    spec = _action(DirectusOperation.create,
                   [("base.first_name", "vorname"), ("base.x", "leer")]).directus
    assert dwa.build_payload(spec, {"base.first_name": "Max", "base.x": ""}) == {"vorname": "Max"}


def _resolve_spec():
    return DirectusWriteSpec(
        operation=DirectusOperation.create, collection="mitarbeiter",
        fieldMap=[DirectusWriteBinding(source="base.contract_company", target="firma",
                                       resolve="company_directus_id")],
        idField="it.directus_id")


def test_build_payload_resolves_company_id():
    spec = _resolve_spec()
    companies = [{"name": "Alpha GmbH", "directus_firma_id": "42"},
                 {"name": "Beta AG", "directus_firma_id": "7"}]
    out = dwa.build_payload(spec, {"base.contract_company": "Beta AG"}, companies=companies)
    assert out == {"firma": "7"}


def test_build_payload_resolve_unknown_company_skips():
    spec = _resolve_spec()
    out = dwa.build_payload(spec, {"base.contract_company": "Gamma KG"},
                            companies=[{"name": "Alpha GmbH", "directus_firma_id": "42"}])
    assert out == {}


def test_build_payload_resolve_company_without_id_skips():
    spec = _resolve_spec()
    out = dwa.build_payload(spec, {"base.contract_company": "Alpha GmbH"},
                            companies=[{"name": "Alpha GmbH", "directus_firma_id": None}])
    assert out == {}


def test_build_payload_raises_when_companies_unreadable(monkeypatch):
    # Transienter Firmen-Ladefehler darf NICHT still zu „alle None" degradieren,
    # sondern muss als DirectusError den Melde-Pfad auslösen.
    import backend.database.settings as settings_mod

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(settings_mod, "get_companies_full", boom)
    with pytest.raises(dc.DirectusError):
        dwa.build_payload(_resolve_spec(), {"base.contract_company": "Alpha GmbH"})


def test_create_stores_id():
    client = FakeClient(created={"id": 42})
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    ch = dwa.execute(_action(DirectusOperation.create, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=NOOP)
    assert ch == {"values": {"mitarbeiter.directus_id": "42"}}
    assert client.calls[0] == ("create", "mitarbeiter", {"vorname": "Max"})


def test_get_or_create_adopts_existing():
    # Geschäftsschlüssel (Personalnummer) → bestehender Datensatz wird übernommen,
    # KEIN zweiter angelegt.
    client = FakeClient(existing_id="7")
    row = {"id": 1, "values": {"base.first_name": "Max", "personal.personal_number": "12345"}}
    act = _action(DirectusOperation.create,
                  [("base.first_name", "vorname"), ("personal.personal_number", "personalnummer")],
                  match_field="personalnummer")
    ch = dwa.execute(act, row, None, None, client=client, on_error=NOOP)
    assert ch == {"values": {"mitarbeiter.directus_id": "7"}}
    assert ("find", "mitarbeiter", "personalnummer", "12345") in client.calls
    assert not any(c[0] == "create" for c in client.calls)


def test_get_or_create_creates_when_absent():
    client = FakeClient(created={"id": 55}, existing_id=None)
    row = {"id": 1, "values": {"base.first_name": "Max", "personal.personal_number": "12345"}}
    act = _action(DirectusOperation.create,
                  [("base.first_name", "vorname"), ("personal.personal_number", "personalnummer")],
                  match_field="personalnummer")
    ch = dwa.execute(act, row, None, None, client=client, on_error=NOOP)
    assert ch == {"values": {"mitarbeiter.directus_id": "55"}}
    assert any(c[0] == "create" for c in client.calls)


def test_block_mode_reraises():
    # onError=block → Fehler DURCHREICHEN (nicht schlucken), damit der Abschluss abbricht.
    reported = []
    client = FakeClient(exc=dc.DirectusError("Directus down"))
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    act = _action(DirectusOperation.create, [("base.first_name", "vorname")], on_error="block")
    with pytest.raises(dc.DirectusError):
        dwa.execute(act, row, None, None, client=client,
                    on_error=lambda *a, **k: reported.append(1))
    assert reported == []            # im Block-Modus NICHT gemeldet, sondern geworfen


def test_continue_mode_swallows_and_reports():
    reported = []
    client = FakeClient(exc=dc.DirectusError("down"))
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    act = _action(DirectusOperation.create, [("base.first_name", "vorname")])  # default continue
    ch = dwa.execute(act, row, None, None, client=client,
                     on_error=lambda *a, **k: reported.append(1))
    assert ch == {} and reported == [1]


def test_create_skips_when_id_present():
    client = FakeClient()
    row = {"id": 1, "values": {"base.first_name": "Max", "mitarbeiter.directus_id": "42"}}
    ch = dwa.execute(_action(DirectusOperation.create, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=NOOP)
    assert ch == {} and client.calls == []       # Doppelanlage-Schutz


def test_update_uses_stored_id():
    client = FakeClient()
    row = {"id": 1, "values": {"base.first_name": "Neu", "mitarbeiter.directus_id": "42"}}
    ch = dwa.execute(_action(DirectusOperation.update, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=NOOP)
    assert ch == {} and client.calls[0] == ("update", "mitarbeiter", "42", {"vorname": "Neu"})


def test_update_without_id_reports():
    errs = []
    client = FakeClient()
    row = {"id": 1, "values": {"base.first_name": "Neu"}}
    ch = dwa.execute(_action(DirectusOperation.update, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=lambda *a: errs.append(a))
    assert ch == {} and errs and client.calls == []


def test_delete_clears_id():
    client = FakeClient()
    row = {"id": 1, "values": {"mitarbeiter.directus_id": "42"}}
    ch = dwa.execute(_action(DirectusOperation.delete, []),
                     row, None, None, client=client, on_error=NOOP)
    assert ch == {"values": {"mitarbeiter.directus_id": None}}
    assert client.calls[0] == ("delete", "mitarbeiter", "42")


def test_directus_error_reports_and_does_not_raise():
    errs = []
    client = FakeClient(exc=dc.DirectusError("down"))
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    ch = dwa.execute(_action(DirectusOperation.create, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=lambda *a: errs.append(a))
    assert ch == {} and len(errs) == 1


def test_create_without_returned_id_reports():
    errs = []
    client = FakeClient(created={})               # Directus liefert keine id
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    ch = dwa.execute(_action(DirectusOperation.create, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=lambda *a: errs.append(a))
    assert ch == {} and len(errs) == 1
