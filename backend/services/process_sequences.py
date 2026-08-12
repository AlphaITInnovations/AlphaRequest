"""
Vergabe fortlaufender Nummern (widget=`server_generated` + `assign_sequence`).

FACHLICH unverändert aus dem Alt-System übernommen: die Personalnummer kommt aus
einem Nummernkreis JE FIRMA (settings-Zeile COMPANIES). Gerechnet wird weiter mit
`compute_next_personalnummer`/`pnr_format` – dieselben getesteten reinen
Funktionen, nur ohne den hartcodierten Onboarding-Pfad drumherum. Auch die
Warn-Schwelle („Nummernkreis wird knapp") und die Audit-Aktionsnamen bleiben, damit
Warn-Mail und Audit-Ansicht unverändert weiterlaufen.

Zwei Dinge sind neu und beide sind Absicht:

**Anspruchs-Ledger statt „ist schon gefüllt?"-Prüfung.** Der Anspruch eines
Auftrags auf „seine" Nummer steht in `process_sequence_claims`. Ein Retry oder ein
zweiter Klick bekommt dieselbe Nummer zurück, statt eine weitere zu verbrennen –
und zwar über einen UNIQUE-Schlüssel, nicht über eine Vorab-Abfrage (die wäre ein
Race).

**Einhängepunkt: der Phasenabschluss, nicht eine Automation.** `assign_due_sequences`
WIRFT bei erschöpftem/unkonfiguriertem Nummernkreis, und der Aufrufer bricht damit
den Phasenabschluss ab. Als Automation-Action wäre die Vergabe wirkungslos:
`process_engine.fire()` fängt jede Action-Exception ab und auditiert sie nur – das
Ticket liefe ohne Nummer weiter, und niemand im Fachbereich würde es merken.

Fällig wird ein Feld beim ABSCHLUSS der ersten Phase, die es führt (die Phase, in
der die Firma feststeht und das Feld im Formular auftaucht) – so wie im Alt-System
die Nummer beim Abschluss der BackOffice-Phase aus der endgültigen „Firma lt.
Arbeitsvertrag" gezogen wurde.
"""
import json
from typing import Any, Callable, Optional

from backend.database import process_tickets as _tickets
from backend.database import process_sequences as _ledger
from backend.database.audit_log import record_audit
from backend.database.personalnummer import (
    PersonalnummerExhausted, PersonalnummerNotConfigured, compute_next_personalnummer,
)
from backend.database.process_tickets import ProcessTicketConflict
from backend.schemas.process_definition import (
    ActionType, FieldDef, PhaseDef, ProcessDefinition, Widget,
)
from backend.services import process_events as events
from backend.utils.config import config
from backend.utils.logger import logger

#: Der einzige heute umgesetzte Nummernkreis: Personalnummern je Firma
#: (settings-Zeile COMPANIES). Ein unbekannter Name ist ein FEHLER, kein No-op –
#: sonst bekäme ein Prozess mit `counter: "rechnungsnummer"` klaglos eine
#: Personalnummer.
COUNTER_PERSONALNUMMER = "personalnummer"
KNOWN_COUNTERS = frozenset({COUNTER_PERSONALNUMMER})


class SequenceError(Exception):
    """Oberklasse aller Vergabe-Fehler (der Aufrufer bricht die Phase ab)."""


class SequenceNotConfigured(SequenceError):
    """Nummernkreis/Firma nicht hinterlegt oder Definition unvollständig (→ 400)."""


class SequenceExhausted(SequenceError):
    """Der Nummernkreis ist erschöpft (→ 409). Kein Retry hilft, nur Erweitern."""


class SequenceCollision(SequenceError):
    """Ledger und Zählerstand laufen auseinander (→ 500). Braucht einen Menschen."""


class SequenceWriteConflict(SequenceError):
    """Die Nummer steht fest, ließ sich aber nicht in den Auftrag schreiben (→ 409).

    Die Nummer ist NICHT verloren: der Anspruch ist committet, ein erneuter
    Abschluss holt sie aus dem Ledger und schreibt sie.
    """


# ── Fälligkeit (reine Logik) ──────────────────────────────────────────────────

def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == [] or v == {}


def assignable_fields(defn: ProcessDefinition) -> list[FieldDef]:
    """Alle Felder, die der Server per Nummernkreis füllt."""
    return [f for f in defn.fields
            if f.widget == Widget.server_generated and f.assign is not None]


def assigning_phase_key(defn: ProcessDefinition, field_key: str) -> Optional[str]:
    """Phase, bei deren ABSCHLUSS das Feld vergeben wird = die ERSTE Phase, die es
    führt. None, wenn keine Phase das Feld einbindet (dann wird es nie vergeben –
    das gehört beim Veröffentlichen abgelehnt, siehe Bericht)."""
    for p in defn.phases:
        if any(fr.ref == field_key for fr in p.fields):
            return p.key
    return None


def due_assignments(defn: ProcessDefinition, phase: Optional[PhaseDef],
                    values: dict) -> list[FieldDef]:
    """Felder, die beim Abschluss DIESER Phase eine Nummer bekommen müssen.

    Ein bereits gefülltes Feld ist nicht mehr fällig – das ist nur die schnelle
    Abkürzung; die echte Idempotenz liegt im Ledger (UNIQUE(ticket_id, field_key)).
    """
    if phase is None:
        return []
    return [f for f in assignable_fields(defn)
            if assigning_phase_key(defn, f.key) == phase.key and _is_empty(values.get(f.key))]


# ── Vergabe ───────────────────────────────────────────────────────────────────

def _default_warn(company_name: str, remaining: int, pnr_to: Any) -> None:
    from backend.services.microsoft_mail import send_personalnummer_warning_mail
    send_personalnummer_warning_mail(company_name, remaining, pnr_to)


def _company_of(defn: ProcessDefinition, field: FieldDef, values: dict) -> str:
    """Firma, deren Nummernkreis gilt – aus dem in `assign.companyRef` genannten Feld."""
    ref = (field.assign.companyRef or "").strip()
    if not ref:
        raise SequenceNotConfigured(
            f"Feld „{field.key}“: `assign.companyRef` fehlt – ohne Firma gibt es "
            f"keinen Nummernkreis.")
    if not any(f.key == ref for f in defn.fields):
        raise SequenceNotConfigured(
            f"Feld „{field.key}“: `assign.companyRef` verweist auf „{ref}“, "
            f"das es im Feld-Katalog nicht gibt.")
    raw = values.get(ref)
    company = raw.strip() if isinstance(raw, str) else ""
    if not company:
        raise SequenceNotConfigured("Bitte zuerst die Firma auswählen "
                                    f"(Feld „{ref}“) – daraus kommt der Nummernkreis.")
    return company


def _assign_one(defn: ProcessDefinition, row: dict, field: FieldDef, *,
                actor: Optional[dict], warn_remaining: int,
                claim: Callable[..., dict], warn: Callable[..., None]) -> str:
    """Eine Nummer für ein Feld holen (oder den bestehenden Anspruch wiederverwenden)."""
    spec = field.assign
    if spec.action != ActionType.assign_sequence:
        raise SequenceNotConfigured(f"Feld „{field.key}“: `assign.action` "
                                    f"„{spec.action.value}“ ist keine Vergabe-Aktion.")
    counter = (spec.counter or "").strip()
    if counter not in KNOWN_COUNTERS:
        raise SequenceNotConfigured(
            f"Feld „{field.key}“: unbekannter Nummernkreis „{counter}“ "
            f"(bekannt: {', '.join(sorted(KNOWN_COUNTERS))}).")

    values = row.get("values") or {}
    company = _company_of(defn, field, values)

    def allocate(companies: list) -> tuple[list, dict]:
        # Reine, getestete Alt-System-Logik – hier läuft KEIN eigener Zähler.
        companies, res = compute_next_personalnummer(companies, company, warn_remaining)
        return companies, {"value": str(res["number"]),
                           "numeric_value": int(str(res["number"])),
                           "scope_key": res["company_name"],
                           "info": res}

    try:
        out = claim(ticket_id=row["id"], field_key=field.key, counter=counter, allocate=allocate)
    except PersonalnummerExhausted as exc:
        _audit_exhausted(row, company, actor, str(exc))
        raise SequenceExhausted(str(exc)) from exc
    except PersonalnummerNotConfigured as exc:
        raise SequenceNotConfigured(str(exc)) from exc
    except _ledger.SequenceNumberCollision as exc:
        raise SequenceCollision(str(exc)) from exc

    alloc = out.get("allocation")
    if alloc is not None:
        # Nur bei einer FRISCHEN Belegung auditieren/warnen – ein Retry darf
        # weder eine zweite Warn-Mail noch einen zweiten Audit-Eintrag erzeugen.
        _audit_assigned(row, field, out, alloc["info"], actor)
        info = alloc["info"]
        if info.get("should_warn"):
            _warn_low(row, info, warn)
    return str(out["value"])


def _audit_assigned(row: dict, field: FieldDef, out: dict, info: dict,
                    actor: Optional[dict]) -> None:
    """Wie im Alt-System (gleicher action-Name → die Audit-Ansicht beschriftet ihn
    schon). Die Nummer steht bewusst NUR im Audit-Log (revisionssicher, nur für
    Admins) – im Ticket-Verlauf wird ausschließlich der FeldSCHLÜSSEL genannt,
    sonst wäre die Feld-Sichtbarkeit über den Verlauf umgehbar."""
    actor = actor or {}
    titel = row.get("title") or ("Auftrag #%s" % row.get("id"))
    record_audit(
        action="personalnummer_assigned", actor_id=actor.get("id"),
        actor_name=actor.get("displayName") or actor.get("email") or "System",
        actor_type="user" if actor.get("id") else "system",
        entity_type="process_ticket", entity_id=str(row.get("id")),
        summary=f"Personalnummer {out['value']} – {titel}",
        details={"number": out["value"], "field": field.key, "counter": out.get("counter"),
                 "company": out.get("scope_key"), "mandant": info.get("mandant"),
                 "remaining": info.get("remaining")},
    )


def _audit_exhausted(row: dict, company: str, actor: Optional[dict], message: str) -> None:
    actor = actor or {}
    record_audit(
        action="personalnummer_exhausted", actor_id=actor.get("id"),
        actor_name=actor.get("displayName") or actor.get("email") or "System",
        actor_type="user" if actor.get("id") else "system",
        entity_type="settings", entity_id="personalnummer",
        summary=f"Firma {company}: Nummernbereich erschöpft",
        details={"company": company, "ticket_id": row.get("id"), "error": message[:500]},
    )


def _warn_low(row: dict, info: dict, warn: Callable[..., None]) -> None:
    """Warn-Schwelle wie heute: Audit-Eintrag + Warn-Mail an TICKET_MAIL.
    Beides best-effort – eine Nummer ist bereits gezogen, ein Mail-Fehler darf
    den Auftrag nicht scheitern lassen."""
    company = info.get("company_name")
    record_audit(
        action="personalnummer_range_low", actor_type="system", actor_name="System",
        entity_type="settings", entity_id="personalnummer",
        summary=f"Firma {company}: nur noch {info.get('remaining')} Nummern frei",
        details={"company": company, "remaining": info.get("remaining"),
                 "pnr_to": info.get("pnr_to"), "ticket_id": row.get("id")},
    )
    try:
        warn(company, info.get("remaining"), info.get("pnr_to"))
    except Exception:
        logger.exception("Personalnummern-Warn-Mail fehlgeschlagen (Firma %s)", company)


def _persist(row: dict, vergeben: dict, store) -> None:
    """Vergebene Nummern in den Auftrag schreiben – MIT rev-Guard.

    Ohne den Guard könnte ein parallel laufender Schreibvorgang (er schreibt den
    kompletten values-Blob zurück) die frisch vergebene Nummer wieder entfernen.
    Bei Konflikt wird EINMAL frisch gelesen und erneut geschrieben; die Nummern
    stehen im Ledger fest, es geht nur noch darum, sie im Auftrag zu verankern.
    """
    for versuch in (1, 2):
        base = dict(row.get("values") or {})
        merged = {**base, **vergeben}
        if merged == base:
            return
        try:
            fresh = store.update_values(row["id"], json.dumps(merged, ensure_ascii=False),
                                        expected_rev=row.get("rev"))
        except ProcessTicketConflict as exc:
            if versuch == 2:
                raise SequenceWriteConflict(
                    f"Auftrag #{row.get('id')} wurde zwischenzeitlich geändert – die "
                    f"vergebene Nummer konnte nicht eingetragen werden. Bitte erneut "
                    f"abschließen (die Nummer bleibt dieselbe).") from exc
            neu = store.get(row["id"])
            if not neu:
                raise SequenceWriteConflict(
                    f"Auftrag #{row.get('id')} nicht mehr vorhanden.") from exc
            row.update(neu)
            continue
        if fresh:
            row.update(fresh)
        else:
            row["values"] = merged
        return


def assign_due_sequences(defn: ProcessDefinition, row: dict, phase: Optional[PhaseDef], *,
                         actor: Optional[dict] = None, warn_remaining: Optional[int] = None,
                         store=None, claim: Optional[Callable[..., dict]] = None,
                         warn: Optional[Callable[..., None]] = None) -> dict:
    """Alle beim Abschluss dieser Phase fälligen Nummern vergeben und eintragen.

    Gibt `{feld_key: nummer}` zurück (leer, wenn nichts fällig war) und
    aktualisiert `row` in place. WIRFT `SequenceError` – der Aufrufer darf die
    Phase dann NICHT weiterschalten.

    `store`/`claim`/`warn` sind injizierbar (Tests, DB-frei).
    """
    store = store or _tickets
    claim = claim or _ledger.claim_company_sequence
    warn = warn or _default_warn
    if warn_remaining is None:
        warn_remaining = int(getattr(config, "PERSONALNUMMER_WARN_REMAINING", 10))

    faellig = due_assignments(defn, phase, row.get("values") or {})
    if not faellig:
        return {}

    vergeben: dict[str, str] = {}
    # Bewusst Feld für Feld und ohne Sammel-Transaktion: jede Nummer ist für sich
    # geclaimt. Scheitert die zweite, bleibt die erste im Ledger stehen und wird
    # beim nächsten Anlauf wiederverwendet – keine verbrannte Nummer.
    for feld in faellig:
        vergeben[feld.key] = _assign_one(defn, row, feld, actor=actor,
                                         warn_remaining=warn_remaining,
                                         claim=claim, warn=warn)

    _persist(row, vergeben, store)

    # Verlauf: NUR die Feldschlüssel. Der Wert selbst unterliegt der
    # Feld-Sichtbarkeit; `process_events.redact` filtert über details["fields"].
    events.system(row, events.UPDATED, phase_key=phase.key if phase else None,
                  details={"fields": sorted(vergeben)})
    return vergeben
