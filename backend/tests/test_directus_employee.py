"""Zuordnung Azure-Login ↔ Directus-Mitarbeiter (services/directus_employee) – ohne Netz."""
import pytest

from backend.services import directus_employee as de
from backend.services.directus_client import DirectusError


@pytest.fixture(autouse=True)
def _clear_cache():
    de.clear_cache()
    yield
    de.clear_cache()


def _q(rows, calls=None):
    def query(coll, **kw):
        if calls is not None:
            calls.append((coll, kw))
        return list(rows)
    return query


def test_treffer_gibt_datensatz_und_filtert_klein_auf_mail():
    calls = []
    rec = de.lookup_employee(
        "Marco.Schneider@x.de",
        query=_q([{"id": 1, "email": "marco.schneider@x.de"}], calls),
        is_configured=lambda: True)
    assert rec == {"id": 1, "email": "marco.schneider@x.de"}
    coll, kw = calls[0]
    assert coll == "mitarbeitende"
    # Directus speichert die Mail klein → kleingeschrieben vergleichen
    assert kw["filter"] == {"email": {"_eq": "marco.schneider@x.de"}}
    assert kw["limit"] == 1


def test_kein_treffer_gibt_none():
    assert de.lookup_employee("x@y.de", query=_q([]), is_configured=lambda: True) is None


def test_leere_mail_gibt_none_ohne_abfrage():
    calls = []
    assert de.lookup_employee("  ", query=_q([{"id": 1}], calls), is_configured=lambda: True) is None
    assert calls == []


def test_nicht_konfiguriert_wirft_lookup_error():
    with pytest.raises(de.EmployeeLookupError):
        de.lookup_employee("x@y.de", query=_q([]), is_configured=lambda: False)


def test_directus_fehler_wird_zu_lookup_error():
    def boom(coll, **kw):
        raise DirectusError("down", status=502)
    with pytest.raises(de.EmployeeLookupError):
        de.lookup_employee("x@y.de", query=boom, is_configured=lambda: True)


def test_cache_vermeidet_zweite_abfrage_auch_bei_anderer_schreibweise():
    calls = []
    q = _q([{"id": 7, "email": "a@b.de"}], calls)
    r1 = de.lookup_employee("A@B.de", query=q, is_configured=lambda: True, now=lambda: 1000.0)
    r2 = de.lookup_employee("a@b.de", query=q, is_configured=lambda: True, now=lambda: 1100.0)
    assert r1 == r2
    assert len(calls) == 1   # zweiter Aufruf aus dem Cache


def test_cache_laeuft_nach_ttl_ab():
    calls = []
    q = _q([{"id": 7}], calls)
    de.lookup_employee("a@b.de", query=q, is_configured=lambda: True, now=lambda: 1000.0)
    de.lookup_employee("a@b.de", query=q, is_configured=lambda: True, now=lambda: 1000.0 + 100_000)
    assert len(calls) == 2


def test_nicht_gefunden_wird_nicht_gecacht():
    calls = []
    q = _q([], calls)
    de.lookup_employee("a@b.de", query=q, is_configured=lambda: True)
    de.lookup_employee("a@b.de", query=q, is_configured=lambda: True)
    assert len(calls) == 2   # jedes Mal neu, damit ein neu angelegter Datensatz sofort greift


# ── list_employees (Nutzerliste/Cache-Quelle) ────────────────────────────────

def test_list_employees_baut_id_name_mail_klein():
    calls = []
    rows = [
        {"email": "Helmut.Popp@x.org", "first_name": "Helmut", "last_name": "Popp"},
        {"email": "a@b.de", "first_name": "A", "last_name": ""},
        {"email": "", "first_name": "Ohne", "last_name": "Mail"},   # ohne Mail -> raus
        {"first_name": "Gar", "last_name": "Keine"},                 # kein email-Feld -> raus
    ]
    out = de.list_employees(query=_q(rows, calls), is_configured=lambda: True)
    assert out == [
        {"id": "helmut.popp@x.org", "displayName": "Helmut Popp", "mail": "helmut.popp@x.org"},
        {"id": "a@b.de", "displayName": "A", "mail": "a@b.de"},
    ]
    coll, kw = calls[0]
    assert coll == "mitarbeitende"
    assert "email" in kw["fields"] and "first_name" in kw["fields"] and "last_name" in kw["fields"]


def test_list_employees_faellt_auf_mail_zurueck_ohne_namen():
    out = de.list_employees(query=_q([{"email": "x@y.de"}]), is_configured=lambda: True)
    assert out == [{"id": "x@y.de", "displayName": "x@y.de", "mail": "x@y.de"}]


def test_list_employees_nicht_konfiguriert_wirft():
    with pytest.raises(de.EmployeeLookupError):
        de.list_employees(query=_q([]), is_configured=lambda: False)
