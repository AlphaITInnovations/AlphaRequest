# -*- coding: utf-8 -*-
"""Einmaliger Import der Alt-Onboarding-Aufträge aus dem Alt-System als
READ-ONLY, ARCHIVIERTE Aufträge des Prozesses `onboarding-archiv`.

Voraussetzung: der Prozess `onboarding-archiv` (docs/prozesse/onboarding-archiv.json)
ist in der ZIELUMGEBUNG bereits importiert UND veröffentlicht (die Gruppen-Platzhalter
dabei den echten Fachabteilungen zugeordnet).

Ablauf je Alt-Auftrag (nur ticket_type == "zugang-beantragen"):
  - description-JSON → Feldwerte (flach, als Text; true/false → Ja/Nein),
  - Owner = E-Mail aus owner_info (das aktuelle System schlüsselt Nutzende per Mail),
  - Runtime: beide Phasen „erreicht", current_index hinter der letzten Phase
    (= archiviert); in der Phase „beteiligte" werden die TATSÄCHLICH beteiligten
    Fachabteilungen (aus workflow_state, per NAME auf die Gruppen-IDs dieser Umgebung
    gemappt) geseedet → sie sehen den Auftrag im persönlichen Archiv,
  - Original created_at/updated_at bleiben erhalten.

Sicherheits-Standard: DRY-RUN. Es wird NICHTS geschrieben, bis `--commit` gesetzt ist.

    # erst prüfen (kein Schreibzugriff):
    .venv/Scripts/python.exe -m backend.scripts.import_alt_onboarding <pfad/tickets.json>
    # dann wirklich importieren:
    .venv/Scripts/python.exe -m backend.scripts.import_alt_onboarding <pfad/tickets.json> --commit

Erneuter Lauf: bricht ab, wenn bereits `onboarding-archiv`-Aufträge existieren
(Schutz vor Doppelimport), außer mit `--force`.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

ARCHIV_KEY = "onboarding-archiv"
OLD_TYPE = "zugang-beantragen"
_PRIO = {"low": "low", "normal": "normal", "high": "high", "urgent": "urgent", "medium": "normal"}

#: Alt-Fachabteilungsname (klein) → aktueller Fachabteilungsname (klein). Das
#: Alt-„BackOffice" ist heute die „Sekretariat GL".
NAME_ALIASES = {"backoffice": "sekretariat gl"}


def _flatten(d: dict, pre: str = "") -> dict:
    out: dict = {}
    for k, v in (d or {}).items():
        kk = pre + k
        if isinstance(v, dict):
            out.update(_flatten(v, kk + "."))
        else:
            out[kk] = v
    return out


def _as_text(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "Ja" if v else "Nein"
    s = str(v).strip()
    return s or None


def _norm_dt(v: Optional[str]) -> Optional[str]:
    """Alt-Zeitstempel (ISO mit T, evtl. Zeitzone) → MariaDB-DATETIME-Form."""
    if not v:
        return None
    s = str(v).replace("T", " ")
    for sep in ("+", "Z"):
        if sep in s:
            s = s.split(sep)[0]
    return s.strip() or None


def _involved_group_ids(ws, name_to_id: dict, unmapped: set) -> list:
    """Beteiligte Gruppen-IDs aus dem Alt-workflow_state (Zuständigkeits-Gruppen +
    Fachabteilungen), per Namen auf die Ziel-IDs gemappt. Fällt auf IT +
    Personalabteilung zurück, wenn kein workflow_state vorhanden ist."""
    names: set = set()
    if isinstance(ws, str):
        try:
            ws = json.loads(ws)
        except Exception:
            ws = None
    if isinstance(ws, dict):
        for ph in ws.get("phases", []) or []:
            resp = ph.get("responsibility") or {}
            if resp.get("kind") == "group" and resp.get("name"):
                names.add(resp["name"])
            for _gid, dv in (ph.get("departments") or {}).items():
                if dv.get("name"):
                    names.add(dv["name"])
    if not names:
        names = {"IT", "Personalabteilung"}
    ids = []
    for n in sorted(names):
        key = n.strip().lower()
        key = NAME_ALIASES.get(key, key)
        gid = name_to_id.get(key)
        if gid:
            if gid not in ids:
                ids.append(gid)
        else:
            unmapped.add(n)
    return ids


def build_row(ticket: dict, name_to_id: dict, process_version: int,
              unmapped: set) -> Optional[dict]:
    """Reine Aufbereitung EINES Alt-Auftrags → Argument-Dict für create_with_id
    (ohne `id`). Kein DB-Zugriff. None, wenn der Auftrag übersprungen wird."""
    if ticket.get("ticket_type") != OLD_TYPE:
        return None
    try:
        old_id = int(str(ticket.get("id")).strip())
    except Exception:
        return None

    try:
        desc = json.loads(ticket.get("description") or "{}")
    except Exception:
        desc = {}
    values = {k: _as_text(v) for k, v in _flatten(desc).items()}
    values = {k: v for k, v in values.items() if v is not None}

    owner_info = ticket.get("owner_info")
    if isinstance(owner_info, str):
        try:
            owner_info = json.loads(owner_info)
        except Exception:
            owner_info = {}
    email = ((owner_info or {}).get("email") or "").strip().lower()
    owner_id = email or (ticket.get("owner_id") or None)
    owner_name = ticket.get("owner_name") or (owner_info or {}).get("displayName")

    created = _norm_dt(ticket.get("created_at"))
    involved = _involved_group_ids(ticket.get("workflow_state"), name_to_id, unmapped)
    runtime = {
        "current_index": 2, "epoch": 0, "rejected": False, "sla_paused_ms": 0,
        "phases": [
            {"key": "erstellung", "status": "done", "entered_at": created, "departments": []},
            {"key": "beteiligte", "status": "done", "entered_at": created,
             "departments": [{"group": gid, "required": True, "status": "done",
                              "by": None, "by_name": None, "at": None, "note": None}
                             for gid in involved]},
        ],
    }
    return {
        "_old_id": old_id,
        "process_key": ARCHIV_KEY, "process_version": process_version,
        "title": ticket.get("title") or f"Alt-Onboarding #{old_id}",
        "status": "archived",
        "priority": _PRIO.get(str(ticket.get("priority") or "").lower(), "normal"),
        "owner_id": owner_id, "owner_name": owner_name,
        "values_json": json.dumps(values, ensure_ascii=False),
        "runtime_json": json.dumps(runtime, ensure_ascii=False),
        "created_at": created, "updated_at": _norm_dt(ticket.get("updated_at")) or created,
        "_involved": involved,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Alt-Onboarding-Aufträge als Archiv importieren")
    ap.add_argument("tickets_json", help="Pfad zur exportierten tickets.json")
    ap.add_argument("--commit", action="store_true", help="wirklich schreiben (sonst Dry-Run)")
    ap.add_argument("--force", action="store_true", help="trotz bereits vorhandener Archiv-Aufträge")
    args = ap.parse_args()

    from backend.database import process_definitions as pdef
    from backend.database import process_tickets as store
    from backend.database.groups import get_groups
    from backend.database.connection import get_connection

    pub = pdef.get_published(ARCHIV_KEY)
    if not pub or not pub.get("definition"):
        print(f"FEHLER: Prozess „{ARCHIV_KEY}“ ist nicht veröffentlicht. Erst importieren "
              f"und veröffentlichen (docs/prozesse/onboarding-archiv.json).", file=sys.stderr)
        return 2
    version = pub["version"]

    name_to_id = {}
    for g in get_groups():
        nm = (g.get("name") or "").strip().lower()
        if nm:
            name_to_id.setdefault(nm, g.get("id"))

    data = json.load(open(args.tickets_json, encoding="utf-8"))
    unmapped: set = set()
    rows = [r for r in (build_row(t, name_to_id, version, unmapped) for t in data) if r]

    print(f"Alt-Onboarding-Aufträge gefunden: {len(rows)}")
    involved_names = {}
    for r in rows:
        involved_names[len(r["_involved"])] = involved_names.get(len(r["_involved"]), 0) + 1
    print(f"beteiligte Gruppen je Auftrag (Anzahl→Aufträge): {involved_names}")
    if unmapped:
        print(f"WARNUNG: Gruppen-Namen ohne passende Fachabteilung (werden übersprungen): "
              f"{sorted(unmapped)}")
    print("Beispiel:", {k: rows[0][k] for k in ("title", "owner_id", "created_at", "status", "_involved")}
          if rows else "—")

    if not args.commit:
        print("\nDRY-RUN – es wurde nichts geschrieben. Mit --commit ausführen.")
        return 0

    # Doppelimport-Schutz + höchste bestehende id (für kollisionsfreie neue ids)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM process_tickets WHERE process_key=%s", (ARCHIV_KEY,))
        existing = int(cur.fetchone()[0])
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM process_tickets")
        base = int(cur.fetchone()[0])
    finally:
        conn.close()
    if existing and not args.force:
        print(f"FEHLER: Es existieren bereits {existing} „{ARCHIV_KEY}“-Aufträge. "
              f"Mit --force erzwingen (legt Duplikate an!).", file=sys.stderr)
        return 3

    ok = 0
    for r in rows:
        new_id = base + r["_old_id"]
        store.create_with_id(
            id=new_id, process_key=r["process_key"], process_version=r["process_version"],
            title=r["title"], status=r["status"], priority=r["priority"],
            owner_id=r["owner_id"], owner_name=r["owner_name"],
            values_json=r["values_json"], runtime_json=r["runtime_json"],
            created_at=r["created_at"], updated_at=r["updated_at"])
        ok += 1
    print(f"\nImportiert: {ok} Aufträge (ids {base + 1}…{base + max(r['_old_id'] for r in rows)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
