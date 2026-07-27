"""
Einmalige, idempotente Migration der Onboarding-Beschreibung (`zugang-beantragen`)
in das aktuelle Format mit eigenem `base`-Block.

Hintergrund: Früher lagen die Basisdaten (Vor-/Nachname, Firma, Niederlassung,
Kostenstelle) unter `personal`, die private Adresse unter `private_address` und die
Signatur-Firma unter `allgemein.appearance_company`. Seit dem `base`-Block-Umbau
gibt es dafür feste Felder. Diese Migration zieht die Alt-Felder einmalig an ihren
neuen Ort, sodass danach ALLE Onboarding-Tickets identisch (nur über `base`/`it`/…)
angesprochen werden können und keine Legacy-Fallbacks mehr nötig sind.

Die Transformation ist rein (`migrate_onboarding_desc`) und idempotent: bereits
migrierte Tickets bleiben unverändert (kein Schreibzugriff).
"""

import copy
import json

from backend.models.models import TicketType
from backend.utils.logger import logger


# Basisfelder, die im Alt-Format unter `personal` lagen und nach `base` gehören.
# start_date (Arbeitsbeginn) ist seit der Verschiebung in die Basisdaten ebenfalls base.
_BASE_FROM_PERSONAL = ("first_name", "last_name", "contract_company", "location", "cost_center", "start_date")


def migrate_onboarding_desc(desc: dict) -> dict:
    """Alt-Onboarding-Beschreibung ins neue `base`-Format überführen (pure, idempotent).

    - `personal.{first_name,last_name,contract_company,location,cost_center,start_date}` → `base.*`
    - `personal.private_address` → `personal.private_street`
    - `allgemein.appearance_company` → `it.appearance_company`
    Die Alt-Schlüssel (inkl. `allgemein`) werden entfernt. Ein neues Format bleibt
    unverändert (Rückgabe ist dann inhaltsgleich zur Eingabe).
    """
    if not isinstance(desc, dict):
        return desc

    new = copy.deepcopy(desc)

    base = new.get("base")
    if not isinstance(base, dict):
        base = {}

    personal = new.get("personal")
    if isinstance(personal, dict):
        # Basisfelder aus personal nach base ziehen (nur wenn base es noch nicht hat).
        for k in _BASE_FROM_PERSONAL:
            if not base.get(k) and personal.get(k) not in (None, ""):
                base[k] = personal[k]
            personal.pop(k, None)
        # Alte Einzeladresse → neues Straßen-Feld.
        if personal.get("private_address") and not personal.get("private_street"):
            personal["private_street"] = personal["private_address"]
        personal.pop("private_address", None)

    # base ist ab jetzt immer vorhanden (einheitliches Format); Anrede ist im
    # Alt-Format nicht enthalten → leer.
    base.setdefault("salutation", "")
    new["base"] = base

    # Signatur-Firma aus der alten `allgemein`-Sektion in den IT-Block ziehen.
    allgemein = new.get("allgemein")
    if isinstance(allgemein, dict):
        it = new.get("it")
        if not isinstance(it, dict):
            it = {}
        if allgemein.get("appearance_company") and not it.get("appearance_company"):
            it["appearance_company"] = allgemein["appearance_company"]
        if it:
            new["it"] = it
        new.pop("allgemein", None)

    return new


def _write_description_only(ticket_id: int, desc: dict) -> None:
    """Schreibt AUSSCHLIESSLICH die description (kein updated_at-Bump), damit die
    Migration bestehende Tickets in Sortierung/Anzeige nicht „anfasst"."""
    from backend.database.connection import get_connection, _exec
    from backend.database.tickets import TICKET_TABLE

    conn = get_connection()
    try:
        _exec(
            conn,
            f"UPDATE {TICKET_TABLE} SET description=%s WHERE id=%s",
            (json.dumps(desc, ensure_ascii=False), ticket_id),
        )
        conn.commit()
    finally:
        conn.close()


def backfill_onboarding_descriptions() -> int:
    """Alle Onboarding-Tickets einmalig ins neue Format migrieren. Idempotent:
    schreibt nur, wenn sich die Beschreibung tatsächlich ändert. Fehler an einem
    einzelnen Ticket brechen die Migration NICHT ab (werden geloggt und übersprungen)."""
    from backend.database.tickets import list_all_tickets

    count = 0
    for ticket in list_all_tickets():
        tt = ticket.ticket_type.value if hasattr(ticket.ticket_type, "value") else ticket.ticket_type
        if tt != TicketType.zugang_beantragen.value:
            continue
        try:
            old = json.loads(ticket.description or "{}")
        except Exception:
            logger.warning("Onboarding-Migration: Ticket %s hat ungültiges JSON – übersprungen", ticket.id)
            continue
        if not isinstance(old, dict):
            continue
        new = migrate_onboarding_desc(old)
        if new != old:
            try:
                _write_description_only(ticket.id, new)
                count += 1
            except Exception as e:
                logger.warning("Onboarding-Migration: Ticket %s nicht aktualisiert: %s", ticket.id, e)
    if count:
        logger.info("Onboarding-Beschreibungen ins neue base-Format migriert: %s", count)
    return count
