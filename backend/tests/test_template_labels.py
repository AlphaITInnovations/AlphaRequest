"""Dokument-Vorlagen-Typen (DOCUMENT_TEMPLATE_LABELS): Registry + Baseline.

Reine Settings-Logik – der DB-Zugriff (settings_get/settings_set) wird durch einen
In-Memory-Store ersetzt."""

import pytest

from backend.database import settings as s


@pytest.fixture
def store(monkeypatch):
    d: dict = {}
    monkeypatch.setattr(s, "settings_get", lambda key, default=None: d.get(key, default))
    monkeypatch.setattr(s, "settings_set", lambda key, val: d.__setitem__(key, val))
    return d


class TestTemplateLabels:
    def test_set_dedups_case_insensitive(self, store):
        labels = s.set_template_labels(["Arbeitsvertrag", "Kündigung", "  arbeitsvertrag "])
        assert [l["name"] for l in labels] == ["Arbeitsvertrag", "Kündigung"]
        assert all(l["placeholders"] is None for l in labels)

    def test_empty_names_skipped(self, store):
        labels = s.set_template_labels(["", "   ", "Arbeitsvertrag"])
        assert [l["name"] for l in labels] == ["Arbeitsvertrag"]

    def test_get_label_case_insensitive(self, store):
        s.set_template_labels(["Arbeitsvertrag"])
        assert s.get_template_label("ARBEITSVERTRAG")["name"] == "Arbeitsvertrag"
        assert s.get_template_label("fehlt") is None

    def test_baseline_set_and_read(self, store):
        s.set_template_labels(["Arbeitsvertrag"])
        s.set_template_label_baseline("arbeitsvertrag", ["vorname", "gehalt"])
        assert s.get_template_label("Arbeitsvertrag")["placeholders"] == ["vorname", "gehalt"]

    def test_baseline_survives_name_list_edit(self, store):
        s.set_template_labels(["Arbeitsvertrag", "Kündigung"])
        s.set_template_label_baseline("Arbeitsvertrag", ["a", "b"])
        # Typ-Liste neu setzen (Kündigung raus, Neu rein) – Baseline von Arbeitsvertrag bleibt.
        labels = s.set_template_labels(["Arbeitsvertrag", "Neu"])
        by = {l["name"]: l for l in labels}
        assert by["Arbeitsvertrag"]["placeholders"] == ["a", "b"]
        assert by["Neu"]["placeholders"] is None
        assert "Kündigung" not in by

    def test_baseline_reset_to_none(self, store):
        s.set_template_labels(["Arbeitsvertrag"])
        s.set_template_label_baseline("Arbeitsvertrag", ["a"])
        s.set_template_label_baseline("Arbeitsvertrag", None)
        assert s.get_template_label("Arbeitsvertrag")["placeholders"] is None

    def test_baseline_ignores_unknown_label(self, store):
        s.set_template_labels(["Arbeitsvertrag"])
        s.set_template_label_baseline("Gibtsnicht", ["x"])   # legt keinen Typ an
        assert s.get_template_label_names() == ["Arbeitsvertrag"]
