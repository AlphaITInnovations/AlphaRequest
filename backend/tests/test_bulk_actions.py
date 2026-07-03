"""Unit-Tests für die reine Bulk-Aktions-Logik (ohne DB)."""

from backend.services.bulk_actions import (
    normalize_bulk_action, required_permission_for_bulk,
)


def test_normalize_akzeptiert_bekannte_aktionen():
    assert normalize_bulk_action("archive") == "archive"
    assert normalize_bulk_action("delete") == "delete"


def test_normalize_trimmt_und_lowercased():
    assert normalize_bulk_action("  ARCHIVE ") == "archive"
    assert normalize_bulk_action("Delete") == "delete"


def test_normalize_unbekannt_ist_none():
    assert normalize_bulk_action("nuke") is None
    assert normalize_bulk_action("") is None
    assert normalize_bulk_action(None) is None


def test_delete_braucht_admin():
    assert required_permission_for_bulk("delete") == "admin"


def test_archive_braucht_manage():
    assert required_permission_for_bulk("archive") == "manage"
