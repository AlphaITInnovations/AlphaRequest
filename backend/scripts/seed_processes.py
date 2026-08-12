#!/usr/bin/env python3
"""
Spielt die ausgelieferten Prozess-Definitionen (backend/seeds/processes/) ein.

Warum ein Skript und kein Automatismus:
  * NICHT in `init_db`: das läuft bei jedem Containerstart. Ein Seeder, der bei
    jedem Start über alle Definitionen geht, macht Gruppen-Auflösung und
    Rechte-Migration zu einer Startbedingung – und ein Fehlschlag zu einem
    Startproblem. Einmalig ist einmalig.
  * NICHT im Import-Endpunkt: der nimmt genau EINE Definition entgegen und
    kennt weder Platzhalter noch Alt-Rechte.
Die Fachlogik liegt in `backend/services/seed_definitions.py` – ein
Admin-Endpunkt kann sie später unverändert benutzen.

Ablauf (Trockenlauf ist der Standard, wie bei import_old_tickets.py):
    python backend/scripts/seed_processes.py
    python backend/scripts/seed_processes.py --commit

Basis-Ticket: dessen zuständige Fachabteilung ist installationsspezifisch und
hat keinen kanonischen Namen. Ohne Angabe wird dieser eine Seed übersprungen:
    python backend/scripts/seed_processes.py --basis-group "IT" --commit
    (alternativ Umgebungsvariable SEED_BASIS_TICKET_GROUP)
"""

import argparse
import os
import sys

# App-Root (das Verzeichnis, das `backend/` enthält) auf den Importpfad legen,
# egal von wo das Skript gestartet wird.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.getcwd())

from backend.services.seed_definitions import (  # noqa: E402
    SeedError,
    required_group_names,
    seed_processes,
)

_SYMBOL = {"created": "+", "would_create": "~", "skipped": ".", "error": "!"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Prozess-Definitionen einspielen")
    ap.add_argument("--commit", action="store_true",
                    help="tatsächlich schreiben (ohne diese Angabe: Trockenlauf, schreibt nichts)")
    ap.add_argument("--basis-group", default=os.environ.get("SEED_BASIS_TICKET_GROUP"),
                    help="Name der zuständigen Fachabteilung für das Basis-Ticket "
                         "(ohne Angabe wird dieser Seed übersprungen)")
    ap.add_argument("--skip-permissions", action="store_true",
                    help="Erstellrechte NICHT aus dem Alt-System übernehmen")
    ap.add_argument("--draft", action="store_true",
                    help="nur als Entwurf anlegen, nicht veröffentlichen "
                         "(Achtung: Entwürfe sind nicht anlegbar)")
    ap.add_argument("--only", action="append", metavar="KEY",
                    help="nur diesen Prozess-Schlüssel einspielen (mehrfach erlaubt)")
    args = ap.parse_args()

    try:
        report = seed_processes(
            commit=args.commit,
            basis_group_name=args.basis_group,
            with_permissions=not args.skip_permissions,
            publish=not args.draft,
            only=set(args.only) if args.only else None,
        )
    except SeedError as e:
        print(f"ABBRUCH: {e}")
        return 2

    print(f"Pflichtgruppen: {', '.join(required_group_names())}")
    if report.angelegte_gruppen:
        print(f"Neu angelegte Gruppen: {', '.join(report.angelegte_gruppen)}")
    if report.fehlende_gruppen:
        print(f"Fehlende Gruppen (würden mit --commit angelegt): "
              f"{', '.join(report.fehlende_gruppen)}")
    print()

    for o in report.outcomes:
        print(f" {_SYMBOL.get(o.aktion, '?')} {(o.key or o.datei):28} {o.meldung}")
        if o.create_permissions:
            cp = o.create_permissions
            print(f"     Erstellrechte: everyone={cp['everyone']} "
                  f"groups={len(cp['groups'])} users={len(cp['users'])}")
        for gid in o.wirkungslose_gruppen:
            print(f"     WIRKUNGSLOS, nicht übernommen: Gruppe {gid} – may_create sieht nur "
                  f"interne Fachabteilungen, keine AD-Gruppen")
        for w in o.warnungen:
            print(f"     WARNUNG: {w}")

    kopf = "COMMIT" if args.commit else "TROCKENLAUF (nichts geschrieben)"
    print(f"\n{kopf}: {report.erstellt} angelegt/anzulegen, "
          f"{report.uebersprungen} übersprungen, {report.fehler} Fehler.")
    return 1 if report.fehler else 0


if __name__ == "__main__":
    sys.exit(main())
