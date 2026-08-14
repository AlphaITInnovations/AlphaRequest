#!/usr/bin/env python3
"""
Spielt die ausgelieferten Prozess-Definitionen (backend/seeds/processes/) ein.

Warum für DIESE Prozesse kein Automatismus:
  * NICHT in `init_db`: das läuft bei jedem Containerstart. Ein Seeder, der bei
    jedem Start über alle Definitionen geht, macht Gruppen-Auflösung und
    Rechte-Migration zu einer Startbedingung – und ein Fehlschlag zu einem
    Startproblem. Einmalig ist einmalig. (Die System-Prozesse laufen dort
    trotzdem mit: sie brauchen weder Gruppen noch Alt-Rechte, siehe unten.)
  * NICHT im Import-Endpunkt: der nimmt genau EINE Definition entgegen und
    kennt weder Platzhalter noch Alt-Rechte.
Die Fachlogik liegt in `backend/services/seed_definitions.py`; derselbe Lauf
steckt hinter `POST /processes:seed` – dieses Skript ist der Weg über die Shell,
nicht mehr der einzige.

Die System-Prozesse (heute das Basis-Ticket) lässt der Lauf AUS und sagt das je
Zeile: die pflegt der Anwendungsstart selbst
(`seed_definitions.ensure_system_processes`), weil die Anwendung ohne sie
unbenutzbar wäre.

Ablauf (Trockenlauf ist der Standard):
    python backend/scripts/seed_processes.py
    python backend/scripts/seed_processes.py --commit

Konfiguration braucht der Lauf keine: alle ausgelieferten Prozesse kommen mit
Platzhaltern aus, die sich aus den Pflichtgruppen auflösen lassen. (Das
Basis-Ticket brauchte früher eine per --basis-group genannte Fachabteilung –
seine Zuständigkeit steht jetzt in einem Feld des Auftrags und wird beim Anlegen
gewählt, nicht in der Definition hinterlegt.)
"""

import argparse
import os
import sys

# App-Root (das Verzeichnis, das `backend/` enthält) auf den Importpfad legen,
# egal von wo das Skript gestartet wird.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.getcwd())

# WICHTIG, nicht wegoptimieren: dieser Import lädt die `.env` (load_dotenv in
# backend/utils/config.py). Die DB-Verbindung liest MARIADB_DSN direkt aus der
# Umgebung – ohne diesen Import ist sie None und der Lauf endete in einem
# SQLAlchemy-Traceback („Expected string or URL object, got None") statt in einer
# lesbaren Meldung. Der App-Prozess importiert config über main.py, ein Skript nicht.
from backend.utils.config import config  # noqa: E402,F401
from backend.services.seed_definitions import (  # noqa: E402
    SeedError,
    required_group_names,
    seed_processes,
)


def _dsn_pruefen() -> None:
    """Ohne Datenbank-Adresse gibt es nichts einzuspielen – das gehört als Satz
    gesagt, nicht als Traceback."""
    if not (os.getenv("MARIADB_DSN") or "").strip():
        print("FEHLER: MARIADB_DSN ist nicht gesetzt.\n"
              "Erwartet wird sie in der .env im Projektverzeichnis (dieselbe, die "
              "die Anwendung nutzt) oder in der Umgebung.", file=sys.stderr)
        raise SystemExit(2)


_SYMBOL = {"created": "+", "would_create": "~", "skipped": ".", "error": "!"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Prozess-Definitionen einspielen")
    ap.add_argument("--commit", action="store_true",
                    help="tatsächlich schreiben (ohne diese Angabe: Trockenlauf, schreibt nichts)")
    ap.add_argument("--skip-permissions", action="store_true",
                    help="Erstellrechte NICHT aus dem Alt-System übernehmen")
    ap.add_argument("--draft", action="store_true",
                    help="nur als Entwurf anlegen, nicht veröffentlichen "
                         "(Achtung: Entwürfe sind nicht anlegbar)")
    ap.add_argument("--only", action="append", metavar="KEY",
                    help="nur diesen Prozess-Schlüssel einspielen (mehrfach erlaubt)")
    args = ap.parse_args()
    _dsn_pruefen()

    try:
        report = seed_processes(
            commit=args.commit,
            with_permissions=not args.skip_permissions,
            publish=not args.draft,
            only=set(args.only) if args.only else None,
        )
    except SeedError as e:
        print(f"ABBRUCH: {e}")
        return 2
    except Exception as e:
        # Häufigster Fall in der Praxis: die Datenbank ist von hier nicht
        # erreichbar (falsche Adresse, kein Netz, Container nicht gestartet). Ein
        # SQLAlchemy-/pymysql-Traceback beantwortet das nicht – die Ursache gehört
        # als Satz gesagt, samt Ziel, damit man die Adresse prüfen kann.
        ziel = (os.getenv("MARIADB_DSN") or "").split("@")[-1] or "unbekannt"
        print(f"ABBRUCH: Datenbank nicht erreichbar oder Lauf fehlgeschlagen "
              f"(Ziel: {ziel})\n{type(e).__name__}: {e}", file=sys.stderr)
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
