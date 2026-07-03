"""Reine Logik rund um Firmen-Normalisierung und Personalnummern-Formatierung."""

from backend.database.settings import (
    normalize_company, pnr_width, pnr_format,
    _digits_or_none, _int_or_none, _str_or_none,
)


class TestDigitsOrNone:
    def test_leading_zeros_preserved(self):
        assert _digits_or_none("00896") == "00896"

    def test_int_coerced_to_string(self):
        assert _digits_or_none(896) == "896"

    def test_whitespace_stripped(self):
        assert _digits_or_none("  12 ") == "12"

    def test_empty_and_none(self):
        assert _digits_or_none("") is None
        assert _digits_or_none(None) is None

    def test_non_digits_rejected(self):
        assert _digits_or_none("12a") is None
        assert _digits_or_none("abc") is None


class TestIntOrNone:
    def test_values(self):
        assert _int_or_none("5") == 5
        assert _int_or_none(5) == 5
        assert _int_or_none("007") == 7

    def test_empty_none_invalid(self):
        assert _int_or_none("") is None
        assert _int_or_none(None) is None
        assert _int_or_none("x") is None


class TestStrOrNone:
    def test_strip(self):
        assert _str_or_none("  Alpha ") == "Alpha"

    def test_empty_variants(self):
        assert _str_or_none("") is None
        assert _str_or_none(None) is None
        assert _str_or_none("   ") is None


class TestNormalizeCompany:
    def test_from_plain_string(self):
        assert normalize_company("  AlphaConsult  ") == {
            "name": "AlphaConsult", "pnr_from": None, "pnr_to": None,
            "pnr_current": None, "pnr_warned": False, "mandant": None,
            "pnr_shared_with": None,
        }

    def test_full_dict_keeps_leading_zeros(self):
        c = normalize_company({
            "name": "A", "pnr_from": "00896", "pnr_to": "15999",
            "pnr_current": 900, "pnr_warned": True, "mandant": "100",
        })
        assert c["pnr_from"] == "00896"
        assert c["pnr_to"] == "15999"
        assert c["pnr_current"] == 900
        assert c["pnr_warned"] is True
        assert c["mandant"] == "100"

    def test_int_range_becomes_digit_string(self):
        c = normalize_company({"name": "A", "pnr_from": 10000, "pnr_to": 19999})
        assert c["pnr_from"] == "10000"
        assert c["pnr_to"] == "19999"

    def test_invalid_range_becomes_none(self):
        c = normalize_company({"name": "A", "pnr_from": "abc", "pnr_to": ""})
        assert c["pnr_from"] is None
        assert c["pnr_to"] is None

    def test_shared_with_normalized(self):
        c = normalize_company({"name": "B", "pnr_shared_with": "  AlphaConsult "})
        assert c["pnr_shared_with"] == "AlphaConsult"

    def test_empty_mandant_and_shared_are_none(self):
        c = normalize_company({"name": "B", "mandant": "", "pnr_shared_with": ""})
        assert c["mandant"] is None
        assert c["pnr_shared_with"] is None

    def test_unknown_type_is_safe(self):
        c = normalize_company(12345)  # weder str noch dict
        assert c["name"] == ""
        assert c["pnr_from"] is None


class TestPnrWidthAndFormat:
    def test_width_equal_lengths(self):
        assert pnr_width({"pnr_from": "00896", "pnr_to": "15999"}) == 5

    def test_width_takes_longer_bound(self):
        assert pnr_width({"pnr_from": "896", "pnr_to": "15999"}) == 5

    def test_width_min_one(self):
        assert pnr_width({"pnr_from": None, "pnr_to": None}) == 1

    def test_format_pads_to_width(self):
        c = {"pnr_from": "00896", "pnr_to": "15999"}
        assert pnr_format(c, 896) == "00896"
        assert pnr_format(c, 1000) == "01000"
        assert pnr_format(c, 15999) == "15999"

    def test_format_without_leading_zeros(self):
        c = {"pnr_from": "10000", "pnr_to": "19999"}
        assert pnr_format(c, 10000) == "10000"
        assert pnr_format(c, 12345) == "12345"
