"""Ebene-1: Automations-Aktion directus_write (services/directus_write_action) – ohne Netz."""
from backend.schemas.process_definition import (
    Action, DirectusOperation, DirectusWriteBinding, DirectusWriteSpec,
)
from backend.services import directus_client as dc
from backend.services import directus_write_action as dwa


class FakeClient:
    DirectusError = dc.DirectusError

    def __init__(self, created=None, exc=None):
        self.created = created if created is not None else {"id": 99}
        self.exc = exc
        self.calls = []

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


def _action(op, field_map, id_field="mitarbeiter.directus_id"):
    return Action(type="directus_write", directus=DirectusWriteSpec(
        operation=op, collection="mitarbeiter",
        fieldMap=[DirectusWriteBinding(source=s, target=t) for s, t in field_map],
        idField=id_field))


NOOP = lambda *a, **k: None  # noqa: E731


def test_build_payload_skips_empty():
    spec = _action(DirectusOperation.create,
                   [("base.first_name", "vorname"), ("base.x", "leer")]).directus
    assert dwa.build_payload(spec, {"base.first_name": "Max", "base.x": ""}) == {"vorname": "Max"}


def test_create_stores_id():
    client = FakeClient(created={"id": 42})
    row = {"id": 1, "values": {"base.first_name": "Max"}}
    ch = dwa.execute(_action(DirectusOperation.create, [("base.first_name", "vorname")]),
                     row, None, None, client=client, on_error=NOOP)
    assert ch == {"values": {"mitarbeiter.directus_id": "42"}}
    assert client.calls[0] == ("create", "mitarbeiter", {"vorname": "Max"})


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
