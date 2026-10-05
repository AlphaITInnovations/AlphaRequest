"""Ebene-1: resolve_company_template – firmenweite Übernahme (documents_shared_with)
UND Pro-Dokument-Verweis (ref_company), je ein Sprung. Ohne DB (get_template +
template_source_company injiziert über monkeypatch)."""
from backend.database import company_templates as ctpl
from backend.database import settings as settings_db


def _patch(monkeypatch, rows, shared=None):
    """rows: {(firma, typ): zeile}; shared: {firma: quelle} (documents_shared_with)."""
    monkeypatch.setattr(ctpl, "get_template", lambda c, n: rows.get((c, n)))
    monkeypatch.setattr(settings_db, "template_source_company",
                        lambda c: (shared or {}).get(c, c))


def _file(company, name, path):
    return {"company": company, "name": name, "stored_path": path, "ref_company": None}


def _ref(company, name, ref):
    return {"company": company, "name": name, "stored_path": None, "ref_company": ref}


def test_own_file(monkeypatch):
    _patch(monkeypatch, {("A", "AV"): _file("A", "AV", "a.docx")})
    assert ctpl.resolve_company_template("A", "AV")["stored_path"] == "a.docx"


def test_per_document_ref_one_hop(monkeypatch):
    _patch(monkeypatch, {("A", "AV"): _ref("A", "AV", "B"),
                         ("B", "AV"): _file("B", "AV", "b.docx")})
    assert ctpl.resolve_company_template("A", "AV")["stored_path"] == "b.docx"


def test_company_level_inherit(monkeypatch):
    _patch(monkeypatch, {("Alpha", "AV"): _file("Alpha", "AV", "al.docx")},
           shared={"Beta": "Alpha"})
    assert ctpl.resolve_company_template("Beta", "AV")["stored_path"] == "al.docx"


def test_company_level_then_per_document(monkeypatch):
    # Beta übernimmt alles von Alpha; Alpha verweist für AV auf Gamma.
    _patch(monkeypatch, {("Alpha", "AV"): _ref("Alpha", "AV", "Gamma"),
                         ("Gamma", "AV"): _file("Gamma", "AV", "g.docx")},
           shared={"Beta": "Alpha"})
    assert ctpl.resolve_company_template("Beta", "AV")["stored_path"] == "g.docx"


def test_dangling_ref_returns_none(monkeypatch):
    # A verweist auf B, aber B hat keine AV-Datei → None (kein Absturz).
    _patch(monkeypatch, {("A", "AV"): _ref("A", "AV", "B")})
    assert ctpl.resolve_company_template("A", "AV") is None


def test_no_template_none(monkeypatch):
    _patch(monkeypatch, {})
    assert ctpl.resolve_company_template("A", "AV") is None
