"""
Datenübergabe Einstellung (Prozess 1) → Onboarding nach Vertragsrücklauf (Prozess 2).

`build_p2_description` ist rein/ohne DB und daher gut testbar; die Orchestrierung
(Ticket anlegen, Workflow aufbauen, Zuständigkeit setzen, verlinken, benachrichtigen)
liegt in `backend/api/v1/tickets.py::_spawn_onboarding_process`, weil sie den Ticket-
Manager, den Workflow-Aufbau und die Mail-Benachrichtigung braucht.
"""

import copy


# Personal-Felder, die NICHT nach P2 übernommen werden. Gehalt/Konditionen werden
# in Prozess 2 nicht mehr gebraucht – sie dort mitzuführen wäre nur unnötiges
# Leak-Risiko (sie sind streng vertraulich).
_P2_PERSONAL_EXCLUDE = ("salary", "conditions")


def build_p2_description(p1_desc: dict, p1_id: int) -> dict:
    """Baut die P2-Beschreibung aus der P1-Beschreibung.

    Übernommen werden die Basisdaten (`base`) und der Personal-Block OHNE die
    vertraulichen Felder Gehalt/Konditionen (die bleiben ausschließlich in P1).
    Die übrigen HR-Felder sowie IT/Signatur und Fuhrpark bleiben leer und werden
    erst in Prozess 2 gefüllt. `_origin_process` verlinkt zurück auf das
    Einstellungs-Ticket.
    """
    if not isinstance(p1_desc, dict):
        p1_desc = {}

    personal = {
        k: v for k, v in copy.deepcopy(p1_desc.get("personal") or {}).items()
        if k not in _P2_PERSONAL_EXCLUDE
    }
    return {
        "base": copy.deepcopy(p1_desc.get("base") or {}),
        "personal": personal,
        "_origin_process": p1_id,
    }
