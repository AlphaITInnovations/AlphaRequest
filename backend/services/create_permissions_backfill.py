"""Erstellrechte des Alt-Systems in `createPermissions` der Prozesse übernehmen.

Im Alt-System lag „wer darf Typ X anlegen?" an zwei Stellen:

* je Nutzer als `extra_permission` `create_<typ>` (siehe
  `ticket_permissions.load_ticket_permissions`), und
* je Tickettyp als Gruppenliste in der Tabelle `ticket_group_permissions`
  (siehe `ticket_permissions.load_group_ticket_permissions`). Diese Liste
  mischt drei Dinge: den Sentinel `__everyone__`, Azure-AD-Gruppen-IDs und
  IDs interner Fachabteilungen.

Im neuen System steht das Recht in der Definition (`CreatePermissions`).

WICHTIG – nicht jede Alt-Gruppe wirkt weiter: `process_permissions.may_create`
bekommt die Gruppen des Nutzers heute ausschließlich aus
`groups.get_group_ids_for_user()` (so rufen es `api/v1/processes.list_processes`
und `api/v1/process_tickets.create_process_ticket` auf). Das sind NUR interne
Fachabteilungen – die AD-Gruppen aus dem Login-Token (`user["groups"]`, wie sie
`ticket_permissions.can_user_create_ticket` im Alt-System noch bekam) erreichen
die Prüfung nie. Eine AD-Gruppen-ID in `createPermissions.groups` wäre also
totes Recht. Deshalb wandert sie hier NICHT stillschweigend mit, sondern wird
als `ineffective_groups` zurückgemeldet – die Ehrlichkeits-Regel gilt auch für
eine Migration.

Reine Abbildung ohne DB-Zugriff (`build_create_permissions`), damit sie testbar
ist; das Laden der Altdaten steckt in `load_legacy_permissions`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

#: Sentinel aus `ticket_permissions.EVERYONE`. Hier bewusst als eigene Konstante:
#: dieses Modul soll den Cutover überleben, an dem das Alt-Modul verschwindet.
#: Der Test `test_create_permissions_backfill` hält beide Werte deckungsgleich.
EVERYONE_SENTINEL = "__everyone__"

#: Alt-TicketType → Prozess-Schlüssel. EXPLIZIT, nicht aus Namen abgeleitet:
#: dass beide heute gleich heißen, ist Zufall der Migration und kein Vertrag.
LEGACY_TYPE_TO_PROCESS_KEY: dict[str, str] = {
    "hardware": "hardware",
    "niederlassung-anmelden": "niederlassung-anmelden",
    "niederlassung-schliessen": "niederlassung-schliessen",
    "niederlassung-umzug": "niederlassung-umzug",
    "einstellung": "einstellung",
    "zugang-beantragen": "zugang-beantragen",
    "zugang-sperren": "zugang-sperren",
    "marketing-stellenanzeige": "marketing-stellenanzeige",
    "hotelbuchung": "hotelbuchung",
    "basis-ticket": "basis-ticket",
}


@dataclass
class CreatePermissionsBackfill:
    """Ergebnis der Abbildung."""
    #: Prozess-Schlüssel → {"everyone": bool, "groups": [...], "users": [...]}
    permissions: dict[str, dict] = field(default_factory=dict)
    #: Prozess-Schlüssel → Alt-Gruppen-IDs, die `may_create` nie sieht
    #: (AD-Gruppen oder gelöschte Fachabteilungen). NICHT übernommen.
    ineffective_groups: dict[str, list[str]] = field(default_factory=dict)
    #: Alt-Tickettypen ohne Ziel-Prozess (Rechte gehen verloren – sichtbar machen).
    unmapped_types: list[str] = field(default_factory=list)


def build_create_permissions(
    user_permissions: dict[str, list[str]],
    group_permissions: dict[str, list[str]],
    *,
    department_group_ids: Iterable[str],
    everyone_sentinel: str = EVERYONE_SENTINEL,
) -> CreatePermissionsBackfill:
    """Bildet die Alt-Rechte auf `createPermissions` ab.

    user_permissions:  Tickettyp → User-IDs (load_ticket_permissions)
    group_permissions: Tickettyp → Gruppen-IDs inkl. Sentinel
                       (load_group_ticket_permissions)
    department_group_ids: IDs der internen Fachabteilungen – nur diese wirken.
    """
    fachabteilungen = {g for g in (department_group_ids or ()) if g}
    ergebnis = CreatePermissionsBackfill()

    alle_typen = sorted(set(user_permissions or {}) | set(group_permissions or {}))
    for typ in alle_typen:
        key = LEGACY_TYPE_TO_PROCESS_KEY.get(typ)
        if not key:
            if (user_permissions or {}).get(typ) or (group_permissions or {}).get(typ):
                ergebnis.unmapped_types.append(typ)
            continue

        roh_gruppen = [g for g in ((group_permissions or {}).get(typ) or []) if g]
        everyone = everyone_sentinel in roh_gruppen
        echte = [g for g in roh_gruppen if g != everyone_sentinel]

        ergebnis.permissions[key] = {
            "everyone": everyone,
            "groups": sorted({g for g in echte if g in fachabteilungen}),
            "users": sorted({u for u in ((user_permissions or {}).get(typ) or []) if u}),
        }
        wirkungslos = sorted({g for g in echte if g not in fachabteilungen})
        if wirkungslos:
            ergebnis.ineffective_groups[key] = wirkungslos

    return ergebnis


def merge_into_definition(defn: dict, perms: Optional[dict]) -> dict:
    """Schreibt die Rechte in eine (bereits geladene) Definition.

    Vereinigung statt Ersetzung: Was der ausgelieferte Seed schon erlaubt (z.B.
    `everyone` beim Basis-Ticket), darf die Migration nicht wieder wegnehmen.
    Gibt eine NEUE Definition zurück, das Original bleibt unangetastet.
    """
    vorhanden = defn.get("createPermissions") or {}
    quelle = perms or {}
    zusammen = {
        "everyone": bool(vorhanden.get("everyone")) or bool(quelle.get("everyone")),
        "groups": sorted(set(vorhanden.get("groups") or []) | set(quelle.get("groups") or [])),
        "users": sorted(set(vorhanden.get("users") or []) | set(quelle.get("users") or [])),
    }
    return {**defn, "createPermissions": zusammen}


def load_legacy_permissions() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Altdaten laden (DB). Getrennt von der Abbildung, damit die testbar bleibt.

    Import bewusst erst hier: nach dem Cutover verschwindet das Alt-Modul, dieses
    Modul soll dann trotzdem noch importierbar sein.
    """
    from backend.services.ticket_permissions import (
        load_group_ticket_permissions,
        load_ticket_permissions,
    )
    return load_ticket_permissions(), load_group_ticket_permissions()
