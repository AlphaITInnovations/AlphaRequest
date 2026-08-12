"""
Verlauf eines Prozess-Auftrags: schreiben (mit Audit) und sichtbar-filtern.

Zwei Dinge, die hier zusammenlaufen müssen:

1. **Ein Schreibweg.** Jeder Verlaufs-Eintrag wird zusätzlich auditiert
   (`audit_log` ist die revisionssichere Ebene und überlebt eine Löschung des
   Auftrags). Deshalb schreibt NUR dieses Modul beides – sonst hätte man
   entweder Einträge ohne Audit oder doppelte Audit-Zeilen (dieselbe Trennung
   wie `services/ticket_history.add_history_event` im Alt-System).

2. **Redaktion beim Lesen.** Ein Eintrag nennt Feldschlüssel („diese Felder
   wurden geändert"). Wer ein Feld nicht sehen darf, darf auch nicht aus dem
   Verlauf erfahren, dass es existiert und wann es gefüllt wurde – sonst wäre
   die Feld-Sichtbarkeit über den Verlauf umgehbar.

`details` darf deshalb NIE Feld-WERTE tragen, nur Schlüssel und Metadaten.
`redact` entfernt einen `values`-Schlüssel defensiv trotzdem.
"""
from typing import Iterable, Optional

from backend.database import process_ticket_events as store
from backend.database.audit_log import record_audit
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_access as acc
from backend.services import process_visibility as vis
from backend.utils.logger import logger

# Kanonische Aktions-Namen. Das Frontend beschriftet danach – neue Namen brauchen
# dort einen Eintrag, sonst zeigt die Timeline den Rohwert.
CREATED = "created"
UPDATED = "updated"
ADVANCED = "advanced"
REJECTED = "rejected"
REOPENED = "reopened"
COMMENT = "comment"
DEPARTMENT_DONE = "department_done"
DEPARTMENT_SKIPPED = "department_skipped"
DEPARTMENT_REJECTED = "department_rejected"
WATCHER_ADDED = "watcher_added"
WATCHER_REMOVED = "watcher_removed"
AUTOMATION_FIRED = "automation_fired"
PRIORITY_CHANGED = "priority_changed"
# Freigabe per Mail-Link (services/process_approval.py)
APPROVAL_DECIDED = "approval_decided"
APPROVAL_SENT_BACK = "approval_sent_back"
APPROVAL_NO_RECIPIENT = "approval_no_recipient"


def _audit(ticket_id: int, action: str, *, actor_id, actor_name, actor_type,
           summary: str, details: Optional[dict]) -> None:
    record_audit(
        action=f"process_ticket_{action}", actor_id=actor_id,
        actor_name=actor_name or "", actor_type=actor_type,
        entity_type="process_ticket", entity_id=str(ticket_id),
        summary=summary, details=details or {},
    )


def write(row: dict, action: str, *, actor_id: Optional[str], actor_name: Optional[str],
          actor_type: str = "user", internal: bool = False,
          body: Optional[str] = None, details: Optional[dict] = None,
          phase_key: Optional[str] = None) -> dict:
    """Verlaufs-Eintrag + Audit schreiben. Fehler werden DURCHGELASSEN.

    Für Einträge, deren Verlust der/die Nutzende bemerken muss (Nachtrag!) –
    der Endpunkt soll dann 500 liefern statt „gespeichert" zu behaupten.
    """
    runtime = row.get("runtime") or {}
    idx = runtime.get("current_index", 0)
    phases = runtime.get("phases") or []
    if phase_key is None and 0 <= idx < len(phases):
        phase_key = phases[idx].get("key")
    ev = store.add_event(
        ticket_id=row["id"], action=action, actor_id=actor_id, actor_name=actor_name,
        actor_type=actor_type, phase_key=phase_key, epoch=int(runtime.get("epoch", 0)),
        internal=internal, body=body, details=details,
    )
    _audit(row["id"], action, actor_id=actor_id, actor_name=actor_name,
           actor_type=actor_type,
           summary=f"Prozess-Ticket #{row['id']}: {action}", details=details)
    return ev


def record(row: dict, action: str, **kwargs) -> Optional[dict]:
    """Wie `write`, aber best-effort: ein Fehler wird geloggt, nicht geworfen.

    Für System-Pfade (Phasenwechsel, Automationen): ein kaputter Verlauf darf
    keinen Phasenübergang verhindern – dieselbe Regel wie beim Audit.
    """
    try:
        return write(row, action, **kwargs)
    except Exception:
        logger.exception("Verlaufs-Eintrag „%s“ für Ticket #%s fehlgeschlagen",
                         action, row.get("id"))
        return None


def system(row: dict, action: str, **kwargs) -> Optional[dict]:
    """Best-effort-Eintrag ohne handelnde Person (Scheduler/Automation)."""
    kwargs.setdefault("actor_id", None)
    kwargs.setdefault("actor_name", "System")
    kwargs["actor_type"] = "system"
    return record(row, action, **kwargs)


# ── Lesen / Redaktion ─────────────────────────────────────────────────────────

def redact(events: Iterable[dict], defn: Optional[ProcessDefinition],
           ctx: vis.ViewerCtx, *, staff: bool) -> list[dict]:
    """Verlauf auf das reduzieren, was diese Person sehen darf.

    * `internal`-Einträge nur für die bearbeitende Seite (`staff`).
    * Genannte Feldschlüssel auf die sichtbaren einschränken. Bleibt davon
      NICHTS übrig, entfällt der Eintrag ganz – „es wurde etwas geändert, was
      Sie nicht sehen dürfen" wäre schon die Information, die verborgen bleiben soll.
    """
    visible = vis.visible_field_keys(defn, ctx) if defn is not None else set()
    out = []
    for ev in events:
        if ev.get("internal") and not staff:
            continue
        det = dict(ev.get("details") or {})
        # Feld-Werte gehören nicht in den Verlauf; defensiv entfernen.
        det.pop("values", None)

        named = det.get("fields")
        if isinstance(named, list) and named:
            keep = [k for k in named if k in visible]
            if not keep:
                continue
            det["fields"] = keep
            if len(keep) != len(named):
                # Ehrlich bleiben: es waren mehr, aber nicht für diese Augen.
                det["fields_hidden"] = len(named) - len(keep)

        single = det.get("field")
        if isinstance(single, str) and single and single not in visible:
            continue

        out.append({**ev, "details": det})
    return out


def for_viewer(row: dict, defn: Optional[ProcessDefinition], user: dict,
               group_ids: Iterable[str], *, limit: int = 100, offset: int = 0,
               ) -> tuple[list[dict], int]:
    """Verlauf eines Auftrags für eine bestimmte Person laden (redigiert).

    `total` ist die UNGEFILTERTE Gesamtzahl – die Blätterung arbeitet auf der
    DB-Reihenfolge, sonst müsste man den ganzen Verlauf lesen, um zu zählen.
    Die Oberfläche zeigt deshalb „x von y" nicht als exakte Sichtbarkeits-Zahl.
    """
    events, total = store.list_for_ticket(row["id"], limit=limit, offset=offset)
    ctx = vis.build_viewer_ctx(user, row, defn, group_ids=set(group_ids))
    staff = acc.is_process_staff(defn, user, group_ids)
    return redact(events, defn, ctx, staff=staff), total
