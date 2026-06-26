#!/usr/bin/env python3
"""
Importiert alte Tickets (JSON-Export) in die NEUE DB mit Phasen-Workflow-Format.

Hintergrund: Die Prod-DB wurde neu angelegt (neues workflow_state-Format mit
"phases"). Die alten Tickets liegen als JSON-Export vor:
  - in_request:  altes Format {"departments": {<alte-gid>: {name,required,status}}}
  - in_progress: workflow_state = null, Person/Gruppe in assignee_*

Das Skript baut pro altem Ticket einen neuen Phasen-`workflow_state`
(via build_workflow, also exakt die App-Logik) und stellt ihn passend zum
alten Status:
  - in_request  -> Durchführungs-Phase aktiv; alte Fachabteilungs-Status werden
                   per NAME auf die NEUEN Gruppen-IDs übernommen.
  - in_progress -> Bearbeitungs-Phase aktiv; Zuständigkeit aus assignee_*
                   (User bleibt per GUID gleich; Gruppe wird per Name neu gemappt).
  - archived    -> alle Phasen erledigt.

Neue Auto-Increment-IDs (alte IDs werden verworfen). Idempotent: ein bereits
importiertes Ticket (gleicher Titel + created_at + owner) wird übersprungen.

Lauf (im Backend-Container, MARIADB_DSN muss gesetzt sein):
    python backend/scripts/import_old_tickets.py /tmp/alpharequest-tickets-pretty.json
    python backend/scripts/import_old_tickets.py /tmp/alpharequest-tickets-pretty.json --commit
Ohne --commit = Dry-Run (zeigt nur, was passieren würde, schreibt nichts).
"""

import os
import sys
import json
import argparse

# App-Root (das Verzeichnis, das `backend/` enthält) auf den Importpfad legen,
# egal von wo das Skript gestartet wird (Skript-Lage UND cwd berücksichtigen).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.getcwd())

from backend.database.connection import get_connection
from backend.database.groups import get_groups
from backend.services.phase_definitions import TICKET_PHASES, PhaseType
from backend.services.workflow_state import build_workflow
from backend.models.models import TicketType


# ── Laden ────────────────────────────────────────────────────────────────────

def load_any(path):
    raw = open(path, encoding="utf-8").read().strip()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        d = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(d, dict):
        d = d.get("tickets") or next((v for v in d.values() if isinstance(v, list)), [d])
    return d


def as_str(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


# ── Workflow-Aufbau ──────────────────────────────────────────────────────────

class _T:
    """Minimaler Ticket-Ersatz – build_workflow braucht nur diese vier Felder."""
    def __init__(self, ticket_type, description, owner_id, owner_name):
        self.ticket_type = ticket_type
        self.description = description
        self.owner_id = owner_id
        self.owner_name = owner_name


def _phase_index(phases, *, type_=None, key=None):
    for i, p in enumerate(phases):
        if key and p.get("key") == key:
            return i
    if type_ is not None:
        # letzte assignment-Phase bevorzugen (Person-Bearbeitung), sonst erste passende
        idxs = [i for i, p in enumerate(phases) if p.get("type") == type_]
        if idxs:
            return idxs[-1] if type_ == PhaseType.assignment.value else idxs[0]
    return None


def _position(workflow, idx):
    for i, p in enumerate(workflow["phases"]):
        p["status"] = "done" if i < idx else ("in_progress" if i == idx else "pending")
    workflow["current_phase_index"] = idx


def build_migrated_workflow(t, name_to_gid, force_status=None):
    ttype = TicketType(t["ticket_type"])
    desc = as_str(t.get("description")) or "{}"
    wf = build_workflow(_T(ttype, desc, t.get("owner_id"), t.get("owner_name")))
    phases = wf["phases"]
    status = force_status or t.get("status")

    # archiviert -> alle Phasen UND alle Fachabteilungen erledigt
    if status == "archived":
        for p in phases:
            p["status"] = "done"
            if p.get("type") == PhaseType.department_review.value:
                for d in p.get("departments", {}).values():
                    d["status"] = "done"
        wf["current_phase_index"] = len(phases)
        return wf, "archived"

    dept_idx = _phase_index(phases, type_=PhaseType.department_review.value)

    # In Durchführung: alte Fachabteilungs-Status per NAME übernehmen
    if status == "in_request" and dept_idx is not None:
        try:
            old_wf = t.get("workflow_state")
            old_wf = json.loads(old_wf) if isinstance(old_wf, str) else (old_wf or {})
        except Exception:
            old_wf = {}
        old_status_by_name = {
            (d.get("name") or "").lower(): d.get("status")
            for d in (old_wf.get("departments") or {}).values()
        }
        for d in phases[dept_idx].get("departments", {}).values():
            nm = (d.get("name") or "").lower()
            if old_status_by_name.get(nm):
                d["status"] = old_status_by_name[nm]
        _position(wf, dept_idx)
        return wf, "in_request"

    # Sonst (in_progress): Person/Gruppe in der Bearbeitungsphase
    target = _phase_index(phases, key="bearbeitung")
    if target is None:
        target = _phase_index(phases, type_=PhaseType.assignment.value)
    if target is None:
        target = 0
    _position(wf, target)

    gid = t.get("assignee_group_id")
    gname = t.get("assignee_group_name")
    aid = t.get("assignee_id")
    aname = t.get("assignee_name")
    if gid and gname:
        phases[target]["responsibility"] = {
            "kind": "group", "id": name_to_gid.get(gname.lower(), gid), "name": gname,
        }
    elif aid and aid != "fachabteilung":
        phases[target]["responsibility"] = {"kind": "user", "id": aid, "name": aname or aid}
    else:
        # Fallback: Ersteller, damit das Ticket nicht ohne Zuständigen dasteht
        phases[target]["responsibility"] = {
            "kind": "user", "id": t.get("owner_id"), "name": t.get("owner_name"),
        }
    return wf, "in_progress"


# ── Hauptlauf ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--commit", action="store_true", help="tatsächlich schreiben (sonst Dry-Run)")
    ap.add_argument("--all-archived", action="store_true",
                    help="alle Tickets als 'archived' importieren (Phasen komplett erledigt)")
    args = ap.parse_args()

    tickets = load_any(args.json_path)
    name_to_gid = {g["name"].lower(): g["id"] for g in get_groups()}
    print(f"{len(tickets)} alte Tickets geladen. Gruppen in neuer DB: {len(name_to_gid)}")

    conn = get_connection()
    inserted = skipped = 0
    try:
        for t in tickets:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM tickets WHERE title=%s AND created_at=%s AND owner_id=%s",
                (t.get("title"), t.get("created_at"), t.get("owner_id")),
            )
            exists = cur.fetchone()
            cur.close()
            if exists:
                skipped += 1
                continue

            eff_status = "archived" if args.all_archived else t.get("status")
            wf, mode = build_migrated_workflow(t, name_to_gid, force_status=eff_status)

            row = dict(t)
            row.pop("id", None)
            row["status"] = eff_status
            row["workflow_state"] = json.dumps(wf, ensure_ascii=False)
            for k in ("description", "history", "assignment_history", "ninja_metadata", "owner_info"):
                if k in row:
                    row[k] = as_str(row[k])
            if not row.get("history"):
                row["history"] = "[]"

            cols = list(row.keys())
            collist = ",".join(f"`{c}`" for c in cols)
            placeholders = ",".join(["%s"] * len(cols))

            print(f"  [{mode:10}] {t.get('ticket_type'):18} "
                  f"phase_idx={wf['current_phase_index']}  '{(t.get('title') or '')[:48]}'")

            if args.commit:
                c = conn.cursor()
                c.execute(f"INSERT INTO tickets ({collist}) VALUES ({placeholders})",
                          [row[c2] for c2 in cols])
                c.close()
            inserted += 1

        if args.commit:
            conn.commit()
    finally:
        conn.close()

    head = "COMMIT" if args.commit else "DRY-RUN (nichts geschrieben)"
    print(f"\n{head}: {inserted} würden eingefügt / eingefügt, {skipped} übersprungen (bereits vorhanden).")


if __name__ == "__main__":
    main()
