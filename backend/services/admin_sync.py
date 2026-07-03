"""
Reine Entscheidungslogik für die Synchronisation der Admin-Rolle mit der
Azure-AD-Admin-Gruppe beim Login (ohne DB/I-O, damit unit-testbar).

Grundidee – die Herkunft der Admin-Rolle wird unterschieden:
  * `admin_via_group = True`  → Admin nur aufgrund der AD-Gruppenmitgliedschaft.
    Verlässt der User die Gruppe, wird die Rolle entzogen.
  * `admin_via_group = False` → Rolle manuell in der App vergeben (set_user_role).
    Wird NIE automatisch entzogen – auch wenn der User nicht in der Gruppe ist.

Ein manuell vergebener Admin, der (später) in die AD-Gruppe aufgenommen wird,
wird beim Login als gruppen-basiert adoptiert (Flag → True); solange er NICHT in
der Gruppe ist, bleibt er unangetastet.
"""

from typing import Optional

ROLE_ADMIN = "admin"

ACTION_PROMOTE = "promote"   # role=admin, admin_via_group=1 setzen
ACTION_REVOKE = "revoke"     # gruppen-basierten Admin entziehen (role=none)


def decide_group_admin_action(
    *,
    admin_group_configured: bool,
    groups_authoritative: bool,
    is_in_admin_group: bool,
    current_role: str,
    admin_via_group: bool,
) -> Optional[str]:
    """Entscheidet, ob beim Login etwas an der Admin-Rolle zu ändern ist.

    Gibt ACTION_PROMOTE, ACTION_REVOKE oder None zurück.

    - Nur aktiv, wenn eine Admin-Gruppe konfiguriert ist UND der groups-Claim
      verlässlich vorliegt (kein „groups overage" → sonst wüssten wir die
      Mitgliedschaft nicht sicher und fassen nichts an).
    - In der Gruppe: sicherstellen, dass der User (gruppen-basierter) Admin ist.
    - Nicht in der Gruppe: nur einen gruppen-basierten Admin entziehen. Manuell
      vergebene Rollen (admin_via_group=False) bleiben unberührt.
    """
    if not (admin_group_configured and groups_authoritative):
        return None

    if is_in_admin_group:
        if current_role != ROLE_ADMIN or not admin_via_group:
            return ACTION_PROMOTE
        return None

    if current_role == ROLE_ADMIN and admin_via_group:
        return ACTION_REVOKE
    return None
