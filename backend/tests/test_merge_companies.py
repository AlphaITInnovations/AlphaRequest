"""Reine Merge-Logik merge_companies (kein DB-Zugriff)."""

from backend.database.settings import merge_companies, normalize_company


def existing(*dicts):
    return [normalize_company(d) for d in dicts]


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
