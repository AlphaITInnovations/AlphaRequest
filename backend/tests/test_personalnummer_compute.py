"""Reine Vergabe-Logik compute_next_personalnummer (kein DB-Zugriff)."""

import pytest

from backend.database.personalnummer import (
    compute_next_personalnummer, PersonalnummerNotConfigured, PersonalnummerExhausted,
)
from backend.database.settings import normalize_company


def companies(*dicts):
    return [normalize_company(d) for d in dicts]


class TestOwnRange:
    def test_first_assignment_starts_at_from(self):
        cs = companies({"name": "A", "pnr_from": "00896", "pnr_to": "00899"})
        updated, res = compute_next_personalnummer(cs, "A", warn_remaining=0)
        assert res["number"] == "00896"
        assert res["remaining"] == 3
        assert res["should_warn"] is False
        assert res["company_name"] == "A"
        assert res["pnr_to"] == "00899"
        assert updated[0]["pnr_current"] == 896

    def test_increments_from_current(self):
        cs = companies({"name": "A", "pnr_from": "00896", "pnr_to": "00899", "pnr_current": 896})
        updated, res = compute_next_personalnummer(cs, "A", 0)
        assert res["number"] == "00897"
        assert res["remaining"] == 2
        assert updated[0]["pnr_current"] == 897

    def test_last_number_then_exhausted(self):
        cs = companies({"name": "A", "pnr_from": "10", "pnr_to": "12", "pnr_current": 11})
        updated, res = compute_next_personalnummer(cs, "A", 0)
        assert res["number"] == "12"
        assert res["remaining"] == 0
        with pytest.raises(PersonalnummerExhausted):
            compute_next_personalnummer(updated, "A", 0)

    def test_exhausted_raises(self):
        cs = companies({"name": "A", "pnr_from": "10", "pnr_to": "10", "pnr_current": 10})
        with pytest.raises(PersonalnummerExhausted):
            compute_next_personalnummer(cs, "A", 0)


class TestWarnThreshold:
    def test_warns_once_when_low(self):
        cs = companies({"name": "A", "pnr_from": "10", "pnr_to": "15", "pnr_current": 13})
        updated, res = compute_next_personalnummer(cs, "A", warn_remaining=2)
        assert res["remaining"] == 1
        assert res["should_warn"] is True
        assert updated[0]["pnr_warned"] is True

    def test_no_double_warn(self):
        cs = companies({"name": "A", "pnr_from": "10", "pnr_to": "15",
                        "pnr_current": 13, "pnr_warned": True})
        _, res = compute_next_personalnummer(cs, "A", warn_remaining=2)
        assert res["should_warn"] is False

    def test_no_warn_when_plenty(self):
        cs = companies({"name": "A", "pnr_from": "10", "pnr_to": "99"})
        _, res = compute_next_personalnummer(cs, "A", warn_remaining=2)
        assert res["should_warn"] is False


class TestNotConfigured:
    def test_unknown_company(self):
        cs = companies({"name": "A", "pnr_from": "1", "pnr_to": "9"})
        with pytest.raises(PersonalnummerNotConfigured):
            compute_next_personalnummer(cs, "Ghost", 0)

    def test_company_without_range(self):
        cs = companies({"name": "A"})
        with pytest.raises(PersonalnummerNotConfigured):
            compute_next_personalnummer(cs, "A", 0)


class TestSharedCounter:
    def test_shared_uses_source_counter(self):
        cs = companies(
            {"name": "A", "pnr_from": "10", "pnr_to": "19"},
            {"name": "B", "pnr_shared_with": "A", "mandant": "m2"},
        )
        updated, res = compute_next_personalnummer(cs, "B", 0)
        assert res["number"] == "10"
        assert res["company_name"] == "A"        # Quelle
        assert res["mandant"] == "m2"            # Mandant der anfragenden Firma B
        assert updated[0]["pnr_current"] == 10   # A hochgezählt
        assert updated[1]["pnr_current"] is None  # B unverändert

    def test_two_companies_share_one_counter(self):
        cs = companies(
            {"name": "A", "pnr_from": "100", "pnr_to": "200"},
            {"name": "B", "pnr_shared_with": "A"},
            {"name": "C", "pnr_shared_with": "A"},
        )
        cs, r1 = compute_next_personalnummer(cs, "B", 0)
        cs, r2 = compute_next_personalnummer(cs, "C", 0)
        cs, r3 = compute_next_personalnummer(cs, "A", 0)
        assert [r1["number"], r2["number"], r3["number"]] == ["100", "101", "102"]

    def test_shared_source_missing(self):
        cs = companies({"name": "B", "pnr_shared_with": "Ghost"})
        with pytest.raises(PersonalnummerNotConfigured):
            compute_next_personalnummer(cs, "B", 0)
