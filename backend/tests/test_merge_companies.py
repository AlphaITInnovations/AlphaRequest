"""Reine Merge-Logik merge_companies (kein DB-Zugriff)."""

from backend.database import settings as settings_db
from backend.database.settings import merge_companies, normalize_company, template_source_company


def existing(*dicts):
    return [normalize_company(d) for d in dicts]


class TestTemplateSourceCompany:
    def _firms(self, monkeypatch, firms):
        monkeypatch.setattr(settings_db, "get_companies_full",
                            lambda: [normalize_company(f) for f in firms])

    def test_resolves_one_hop(self, monkeypatch):
        self._firms(monkeypatch, [{"name": "Alpha GmbH"},
                                  {"name": "Beta GmbH", "documents_shared_with": "Alpha GmbH"}])
        assert template_source_company("Beta GmbH") == "Alpha GmbH"

    def test_case_insensitive_and_canonical(self, monkeypatch):
        # Abweichende Groß-/Kleinschreibung im Auftragswert darf den Hop nicht überspringen.
        self._firms(monkeypatch, [{"name": "Alpha GmbH"},
                                  {"name": "Beta GmbH", "documents_shared_with": "Alpha GmbH"}])
        assert template_source_company("beta gmbh") == "Alpha GmbH"
        # Eigene Firma → kanonischer Name (nicht der abweichend geschriebene Input).
        assert template_source_company("alpha GMBH") == "Alpha GmbH"

    def test_unknown_company_unchanged(self, monkeypatch):
        self._firms(monkeypatch, [{"name": "Alpha GmbH"}])
        assert template_source_company("Gamma GmbH") == "Gamma GmbH"


class TestMergeCompanies:
    def test_preserves_current_from_existing(self):
        ex = existing({"name": "A", "pnr_from": "100", "pnr_to": "200", "pnr_current": 150})
        merged = merge_companies([{"name": "A", "pnr_from": "100", "pnr_to": "200"}], ex)
        assert merged[0]["pnr_current"] == 150

    def test_client_cannot_set_counter(self):
        ex = existing({"name": "A", "pnr_from": "100", "pnr_to": "200", "pnr_current": 150})
        merged = merge_companies(
            [{"name": "A", "pnr_from": "100", "pnr_to": "200", "pnr_current": 999}], ex)
        assert merged[0]["pnr_current"] == 150   # Client-Wert 999 ignoriert

    def test_new_company_fresh(self):
        merged = merge_companies([{"name": "New", "pnr_from": "1", "pnr_to": "9"}], [])
        assert merged[0]["pnr_current"] is None
        assert merged[0]["pnr_warned"] is False

    def test_directus_firma_id_roundtrips(self):
        merged = merge_companies(
            [{"name": "A", "pnr_from": "1", "pnr_to": "9", "directus_firma_id": "42"}], [])
        assert merged[0]["directus_firma_id"] == "42"

    def test_directus_firma_id_defaults_none(self):
        assert normalize_company({"name": "A"})["directus_firma_id"] is None
        assert normalize_company("A")["directus_firma_id"] is None

    def test_sharer_clears_range_and_counter(self):
        merged = merge_companies(
            [{"name": "B", "pnr_shared_with": "A", "pnr_from": "1", "pnr_to": "9", "pnr_current": 5}], [])
        b = merged[0]
        assert b["pnr_shared_with"] == "A"
        assert b["pnr_from"] is None and b["pnr_to"] is None
        assert b["pnr_current"] is None and b["pnr_warned"] is False

    def test_warn_reset_on_range_extension(self):
        ex = existing({"name": "A", "pnr_from": "100", "pnr_to": "200",
                       "pnr_current": 195, "pnr_warned": True})
        merged = merge_companies([{"name": "A", "pnr_from": "100", "pnr_to": "300"}], ex)
        assert merged[0]["pnr_warned"] is False
        assert merged[0]["pnr_current"] == 195

    def test_warn_kept_when_not_extended(self):
        ex = existing({"name": "A", "pnr_from": "100", "pnr_to": "200", "pnr_warned": True})
        merged = merge_companies([{"name": "A", "pnr_from": "100", "pnr_to": "200"}], ex)
        assert merged[0]["pnr_warned"] is True

    def test_dedup_by_name_first_wins(self):
        merged = merge_companies([
            {"name": "A", "pnr_from": "1", "pnr_to": "9"},
            {"name": "A", "pnr_from": "10", "pnr_to": "99"},
        ], [])
        assert len(merged) == 1
        assert merged[0]["pnr_to"] == "9"

    def test_empty_name_skipped(self):
        merged = merge_companies([{"name": "  "}, {"name": "A", "pnr_from": "1", "pnr_to": "9"}], [])
        assert [c["name"] for c in merged] == ["A"]

    def test_documents_shared_with_roundtrips(self):
        merged = merge_companies([{"name": "B", "documents_shared_with": "A"}], [])
        assert merged[0]["documents_shared_with"] == "A"

    def test_documents_shared_with_defaults_none(self):
        assert normalize_company({"name": "A"})["documents_shared_with"] is None
        assert normalize_company("A")["documents_shared_with"] is None

    def test_documents_sharing_independent_of_counter(self):
        # Eigener Nummernbereich UND Vorlagen-Übernahme sind getrennte Achsen.
        merged = merge_companies(
            [{"name": "B", "pnr_from": "1", "pnr_to": "9", "documents_shared_with": "A"}], [])
        b = merged[0]
        assert b["documents_shared_with"] == "A"
        assert b["pnr_from"] == "1" and b["pnr_to"] == "9"   # Bereich bleibt erhalten
