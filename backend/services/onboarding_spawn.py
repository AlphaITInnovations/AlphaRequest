"""
Datenübergabe Einstellung (Prozess 1) → Onboarding nach Vertragsrücklauf (Prozess 2).

`build_p2_description` ist rein/ohne DB und daher gut testbar; die Orchestrierung
(Ticket anlegen, Workflow aufbauen, Zuständigkeit setzen, verlinken, benachrichtigen)
liegt in `backend/api/v1/tickets.py::_spawn_onboarding_process`, weil sie den Ticket-
Manager, den Workflow-Aufbau und die Mail-Benachrichtigung braucht.
"""

import copy


def build_p2_description(p1_desc: dict, p1_id: int) -> dict:
    """Baut die P2-Beschreibung aus der P1-Beschreibung.

    Übernommen werden Basisdaten (`base`), der Titel (`personal.title`) und die
    vertraulichen Informationen (`confidential`). Alle übrigen Felder (weitere
    HR-Daten, IT/Signatur, Fuhrpark) bleiben leer und werden erst in Prozess 2
    gefüllt. `_origin_process` verlinkt zurück auf das Einstellungs-Ticket.
    """
    if not isinstance(p1_desc, dict):
        p1_desc = {}

    base = copy.deepcopy(p1_desc.get("base") or {})
    confidential = copy.deepcopy(p1_desc.get("confidential") or {})

    title = (p1_desc.get("personal") or {}).get("title")
    personal = {"title": title} if title not in (None, "") else {}

    return {
        "base": base,
        "personal": personal,
        "confidential": confidential,
        "_origin_process": p1_id,
    }
