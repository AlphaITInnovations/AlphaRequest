"""
Ebene-1-Tests: reine Logik, KEIN DB-Zugriff.

Die getesteten Funktionen (workflow_state, settings) lesen nur aus im Speicher
übergebenen Objekten/Dicts. Gemeinsame Bau-Helfer liegen in factories.py.
"""

import os
import sys

# Repo-Root sicherheitshalber auf den Pfad (falls pytest ohne pythonpath läuft).
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
