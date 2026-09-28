"""
Ebene-1-Tests: reine Logik, KEIN DB-Zugriff.

Die getesteten Funktionen lesen nur aus im Speicher übergebenen Objekten/Dicts;
wer eine DB braucht, ersetzt den Store durch eine Attrappe.
"""

import os
import sys

import pytest

# Repo-Root sicherheitshalber auf den Pfad (falls pytest ohne pythonpath läuft).
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(autouse=True)
def _kein_echter_db_zugriff(monkeypatch, request):
    """Echten DB-Zugriff SOFORT scheitern lassen statt ins TCP-Timeout zu laufen.

    Ohne das kostete jeder API-Test zig Sekunden: Nebenwirkungen, die einen
    Fehlschlag bewusst wegfangen (`record_audit`, Verlauf, Beobachter-Lookup),
    versuchen eine Verbindung zu einem Server, den es hier nicht gibt – und
    warten jedes Mal auf den Timeout. Ein sofortiger Fehler nimmt denselben Weg,
    nur ohne Wartezeit.

    Angesetzt wird an `_get_pool`, nicht an `get_connection`: viele Module haben
    `get_connection` direkt importiert und hielten sonst ihre eigene Referenz.
    Wer eine DB BRAUCHT, ersetzt den Store durch einen Fake – das ist die Regel
    dieser Test-Ebene (siehe Modul-Docstring). Ausnahme: Tests mit der Marke
    `echter_pool` prüfen den Pool selbst (gegen eine DBAPI-Attrappe).
    """
    if request.node.get_closest_marker("echter_pool"):
        return
    from backend.database import connection

    def _kein_pool(*_a, **_k):
        raise RuntimeError("DB-Zugriff in einem DB-freien Test – bitte Store faken")

    monkeypatch.setattr(connection, "_get_pool", _kein_pool)
