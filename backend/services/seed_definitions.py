"""Ausgelieferte Prozess-Definitionen auflösen, prüfen und einspielen.

Die Seeds unter `backend/seeds/processes/` sind absichtlich ohne Gruppen-IDs
ausgeliefert – IDs sind pro Installation verschieden. Statt IDs stehen dort
Platzhalter (`HIER_GRUPPEN_ID_IT_EINSETZEN` …), die hier gegen die echten
Gruppen der Installation aufgelöst werden.

Warum das eine eigene Schicht ist und nicht im Skript steht: die Auflösung ist
die einzige Stelle, die entscheidet, ob ein Prozess überhaupt funktionsfähig
eingespielt wird. Sie muss testbar sein und soll später von einem
Admin-Endpunkt wiederverwendbar sein.

Zwei Regeln, die den Rest erklären:

* **Fail-closed.** Ein Platzhalter, der es bis in die DB schafft, wird vom
  Schema NICHT bemängelt (es kennt die Gruppen der Installation nicht) – der
  Prozess wäre aber dauerhaft kaputt: niemand ist zuständig, eine
  Fachabteilungs-Phase ließe sich nie abschließen, und in
  `visibility.visibleToGroups` wäre ein vertrauliches Feld für NIEMANDEN
  sichtbar. Deshalb prüft der Seeder das selbst und verweigert den Prozess.
* **Nichts überschreiben.** Existiert der Schlüssel schon – auch nur als
  Entwurf –, wird übersprungen. Eine vom Admin angepasste Definition darf ein
  Seeder nie zurücksetzen.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.database import groups as groupsdb
from backend.database import process_definitions as defstore
from backend.schemas.process_definition import ProcessDefinition
from backend.seeds import process_seed_files
from backend.services import create_permissions_backfill as backfill
from backend.utils.logger import logger


class SeedError(Exception):
    """Der Lauf kann nicht sinnvoll starten (Konfiguration/Gruppen kaputt)."""


# ── Platzhalter → Gruppenname ────────────────────────────────────────────────
#
# Bewusst eine Konstante und keine Ableitung aus dem Platzhalter-Text: „raten"
# würde bei „SEKRETARIAT_GL" → „Sekretariat GL" zufällig klappen und bei
# „FREIGABEHERRLUTZ" → „FreigabeHerrLutz" schon nicht mehr. Die Namen sind die
# der Alt-Workflows (workflow_state._DEPARTMENT_GROUP_NAMES + assign_group),
# damit die bestehenden Gruppen samt Mitgliedern weiterverwendet werden.

PLACEHOLDER_GROUP_NAMES: dict[str, str] = {
    "HIER_GRUPPEN_ID_IT_EINSETZEN": "IT",
    "HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN": "Personalabteilung",
    "HIER_GRUPPEN_ID_FUHRPARK_EINSETZEN": "Fuhrpark",
    "HIER_GRUPPEN_ID_VERWALTUNG_EINSETZEN": "Verwaltung",
    "HIER_GRUPPEN_ID_MARKETING_EINSETZEN": "Marketing",
    "HIER_GRUPPEN_ID_HOTELBUCHUNG_EINSETZEN": "Hotelbuchung",
    "HIER_GRUPPEN_ID_REISESTELLE_EINSETZEN": "Reisestelle",
    "HIER_GRUPPEN_ID_SEKRETARIAT_GL_EINSETZEN": "Sekretariat GL",
    "HIER_GRUPPEN_ID_FREIGABEHERRLUTZ_EINSETZEN": "FreigabeHerrLutz",
}

#: Das Basis-Ticket lässt die zuständige Fachabteilung offen – es gibt dafür
#: KEINEN kanonischen Namen (jede Installation entscheidet das selbst). Ohne
#: Konfiguration wird dieser Seed übersprungen statt kaputt eingespielt.
BASIS_TICKET_PLACEHOLDER = "HIER_GRUPPEN_ID_ZUSTAENDIGE_GRUPPE_EINSETZEN"

#: Gruppen, die ausschließlich automatisch über eine Phase zugewiesen werden
#: (responsibility.kind=group) und deshalb in Auswahl-Dropdowns nichts zu
#: suchen haben. Entspricht `workflow_state.assign_group_names()` des
#: Alt-Systems – nur bei NEUANLAGE gesetzt, ein Admin kann es ändern.
AUTO_ASSIGNED_GROUP_NAMES: list[str] = ["Sekretariat GL", "FreigabeHerrLutz", "Reisestelle"]

#: Erkennt einen Platzhalter, der (noch) nicht aufgelöst ist.
_PLACEHOLDER_RE = re.compile(r"HIER_[A-Z0-9_]*_EINSETZEN")

#: Kennzeichnung im Trockenlauf für Gruppen, die es noch nicht gibt. Muss keine
#: echte ID sein – im Trockenlauf wird nichts geschrieben, geprüft wird nur die
#: Struktur.
_DRY_RUN_ID_PREFIX = "DRYRUN-NEUE-GRUPPE:"


def required_group_names() -> list[str]:
    """Gruppen, die für die ausgelieferten Prozesse existieren MÜSSEN.

    Eigene Namensquelle neben dem Seeder – bewusst nicht aus dem Alt-Modul
    `workflow_state` gelesen, damit die Pflichtgruppen den Cutover überleben.
    (Die Alt-Pflichtgruppe „QM" fehlt hier absichtlich: kein ausgelieferter
    Prozess referenziert sie. Bestehende Gruppen werden nie entfernt.)
    """
    seen: set[str] = set()
    out: list[str] = []
    for name in PLACEHOLDER_GROUP_NAMES.values():
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


# ── Gruppen-Index ────────────────────────────────────────────────────────────

def build_group_index(groups: Iterable[dict]) -> dict[str, str]:
    """Name (kleingeschrieben, getrimmt) → Gruppen-ID.

    Case-INSENSITIV, weil eine Gruppe in der DB „IT" oder „it" heißen kann;
    `get_groupID_from_name` vergleicht exakt und würde hier still danebengreifen.
    Zwei Gruppen mit demselben Namen sind nicht auflösbar – lieber ein Fehler
    als die falsche Gruppe.
    """
    index: dict[str, str] = {}
    doppelt: dict[str, set[str]] = {}
    for g in groups or []:
        name = (g.get("name") or "").strip().lower()
        gid = g.get("id")
        if not name or not gid:
            continue
        if name in index and index[name] != gid:
            doppelt.setdefault(name, {index[name]}).add(gid)
            continue
        index[name] = gid
    if doppelt:
        details = "; ".join(f"„{n}“ → {sorted(ids)}" for n, ids in sorted(doppelt.items()))
        raise SeedError(f"Mehrdeutige Gruppennamen (gleicher Name, verschiedene IDs): {details}")
    return index


# ── Auflösung ────────────────────────────────────────────────────────────────

def replace_placeholders(node: Any, mapping: dict[str, str]) -> Any:
    """Ersetzt Platzhalter NUR an String-Blättern, die exakt einem Platzhalter
    entsprechen.

    Bewusst kein Text-Replace auf dem Rohtext: ein Platzhalter, der in einem
    Prosa-Feld (Hilfetext, Hinweisbox) erwähnt wird, würde dabei zu einer
    Gruppen-ID mutieren.
    """
    if isinstance(node, dict):
        return {k: replace_placeholders(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [replace_placeholders(v, mapping) for v in node]
    if isinstance(node, str):
        return mapping.get(node, node)
    return node


def collect_group_refs(defn: dict) -> list[tuple[str, str]]:
    """Alle Stellen, an denen eine Gruppen-ID STEHT (Pfad, Wert).

    Deckt genau die Stellen ab, an denen eine kaputte ID den Prozess lahmlegt:
    Feld-Sichtbarkeit, Phasen-Zuständigkeit (fest + Abteilungs-Regeln),
    Automations-Empfänger und Erstellrechte.
    """
    out: list[tuple[str, str]] = []

    def _autos(items, base: str) -> None:
        for i, a in enumerate(items or []):
            to = ((a or {}).get("action") or {}).get("to")
            if isinstance(to, str) and to.startswith("group:"):
                out.append((f"{base}[{i}].action.to", to.split(":", 1)[1]))

    for i, f in enumerate(defn.get("fields") or []):
        vis = (f or {}).get("visibility") or {}
        for j, gid in enumerate(vis.get("visibleToGroups") or []):
            out.append((f"fields[{i}]({(f or {}).get('key')}).visibility.visibleToGroups[{j}]", gid))

    _autos(defn.get("automations"), "automations")

    for i, p in enumerate(defn.get("phases") or []):
        pk = (p or {}).get("key")
        r = (p or {}).get("responsibility") or {}
        if r.get("group"):
            out.append((f"phases[{i}]({pk}).responsibility.group", r["group"]))
        for j, dr in enumerate(r.get("rule") or []):
            if (dr or {}).get("group"):
                out.append((f"phases[{i}]({pk}).responsibility.rule[{j}].group", dr["group"]))
        _autos((p or {}).get("automations"), f"phases[{i}]({pk}).automations")

    for j, gid in enumerate(((defn.get("createPermissions") or {}).get("groups") or [])):
        out.append((f"createPermissions.groups[{j}]", gid))

    return [(pfad, wert) for pfad, wert in out if isinstance(wert, str)]


def find_stray_placeholders(node: Any, pfad: str = "") -> list[tuple[str, str]]:
    """Platzhalter-Reste IRGENDWO in der Definition (auch mitten im Text)."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += find_stray_placeholders(v, f"{pfad}.{k}" if pfad else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += find_stray_placeholders(v, f"{pfad}[{i}]")
    elif isinstance(node, str) and _PLACEHOLDER_RE.search(node):
        out.append((pfad, node))
    return out


def check_group_refs(defn: dict, known_group_ids: set[str]) -> list[str]:
    """Fail-closed-Prüfung: unaufgelöste Platzhalter und unbekannte Gruppen-IDs.

    Leere Liste = einspielbar.
    """
    probleme: list[str] = []
    for pfad, wert in collect_group_refs(defn):
        if _PLACEHOLDER_RE.fullmatch(wert):
            probleme.append(f"{pfad}: unaufgelöster Platzhalter „{wert}“")
        elif wert not in known_group_ids:
            probleme.append(f"{pfad}: Gruppen-ID „{wert}“ existiert nicht")
    return probleme


# ── Ergebnis-Berichte ────────────────────────────────────────────────────────

@dataclass
class SeedOutcome:
    """Was mit EINEM Seed passiert ist."""
    datei: str
    key: Optional[str]
    aktion: str                    # created | would_create | skipped | error
    meldung: str = ""
    warnungen: list[str] = field(default_factory=list)
    #: Erstellrechte, die aus dem Alt-System übernommen wurden.
    create_permissions: Optional[dict] = None
    #: Alt-Gruppen-IDs, die `may_create` nie zu sehen bekommt (siehe Modul
    #: create_permissions_backfill) – übernommen wird nur, was auch wirkt.
    wirkungslose_gruppen: list[str] = field(default_factory=list)


@dataclass
class SeedReport:
    commit: bool
    outcomes: list[SeedOutcome] = field(default_factory=list)
    #: Gruppen, die der Lauf angelegt hat (nur bei commit).
    angelegte_gruppen: list[str] = field(default_factory=list)
    #: Pflichtgruppen, die im Trockenlauf noch fehlen.
    fehlende_gruppen: list[str] = field(default_factory=list)

    def _n(self, aktion: str) -> int:
        return sum(1 for o in self.outcomes if o.aktion == aktion)

    @property
    def erstellt(self) -> int:
        return self._n("created") + self._n("would_create")

    @property
    def uebersprungen(self) -> int:
        return self._n("skipped")

    @property
    def fehler(self) -> int:
        return self._n("error")


# ── Hauptlauf ────────────────────────────────────────────────────────────────

def _lade_seed(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8"))


def build_placeholder_mapping(index: dict[str, str],
                              basis_group_name: Optional[str] = None) -> dict[str, str]:
    """Platzhalter → echte Gruppen-ID. Nicht auflösbare Platzhalter fehlen in der
    Abbildung (und fliegen später in der Fail-closed-Prüfung auf)."""
    mapping: dict[str, str] = {}
    for ph, name in PLACEHOLDER_GROUP_NAMES.items():
        gid = index.get(name.strip().lower())
        if gid:
            mapping[ph] = gid
    if basis_group_name:
        gid = index.get(basis_group_name.strip().lower())
        if gid:
            mapping[BASIS_TICKET_PLACEHOLDER] = gid
    return mapping


def seed_processes(*, commit: bool = False,
                   basis_group_name: Optional[str] = None,
                   with_permissions: bool = True,
                   publish: bool = True,
                   only: Optional[set[str]] = None,
                   actor: str = "seed_processes",
                   actor_name: str = "Seeder") -> SeedReport:
    """Spielt die ausgelieferten Prozesse ein.

    `commit=False` (Standard) schreibt NICHTS – weder Prozesse noch Gruppen.
    """
    report = SeedReport(commit=commit)

    # 1. Gruppen. Die konfigurierte Basis-Ticket-Gruppe wird NICHT angelegt: sie
    #    ist eine Entscheidung des Betriebs, kein Standard – ein Tippfehler soll
    #    auffallen, nicht eine leere Gruppe erzeugen.
    vorher = build_group_index(groupsdb.get_groups())
    if basis_group_name and basis_group_name.strip().lower() not in vorher:
        raise SeedError(
            f"Basis-Ticket-Gruppe „{basis_group_name}“ gibt es nicht. "
            f"Vorhandene Gruppen: {', '.join(sorted(vorher)) or '(keine)'}")

    if commit:
        report.angelegte_gruppen = groupsdb.ensure_required_groups(
            required_group_names(), hidden_names=AUTO_ASSIGNED_GROUP_NAMES)
        if report.angelegte_gruppen:
            logger.info("Pflichtgruppen angelegt: %s", ", ".join(report.angelegte_gruppen))
        index = build_group_index(groupsdb.get_groups())
    else:
        index = dict(vorher)
        for name in required_group_names():
            if name.strip().lower() not in index:
                report.fehlende_gruppen.append(name)
                # Ersatz-ID nur für den Trockenlauf: sonst meldete die
                # Fail-closed-Prüfung auf einer frischen DB zehnmal „Platzhalter“,
                # obwohl `--commit` die Gruppe angelegt hätte.
                index[name.strip().lower()] = _DRY_RUN_ID_PREFIX + name

    mapping = build_placeholder_mapping(index, basis_group_name)
    bekannte_ids = set(index.values())

    # 2. Erstellrechte aus dem Alt-System (einmal laden, nicht je Prozess).
    #    Maßstab sind die Gruppen VOR dem Anlegen: nur auf die kann eine
    #    Alt-Berechtigung überhaupt zeigen.
    rechte = None
    if with_permissions:
        alt_user, alt_gruppen = backfill.load_legacy_permissions()
        rechte = backfill.build_create_permissions(
            alt_user, alt_gruppen, department_group_ids=set(vorher.values()))

    # 3. Seeds der Reihe nach.
    for pfad in process_seed_files():
        outcome = _seed_one(pfad, mapping=mapping, bekannte_ids=bekannte_ids,
                            rechte=rechte, only=only, commit=commit, publish=publish,
                            actor=actor, actor_name=actor_name)
        if outcome is not None:
            report.outcomes.append(outcome)

    return report


def _seed_one(pfad: Path, *, mapping: dict[str, str], bekannte_ids: set[str],
              rechte, only: Optional[set[str]], commit: bool, publish: bool,
              actor: str, actor_name: str) -> Optional[SeedOutcome]:
    datei = pfad.name
    try:
        roh = _lade_seed(pfad)
    except Exception as e:
        return SeedOutcome(datei, None, "error", f"nicht lesbar: {e}")

    key = roh.get("key")
    if only and key not in only:
        return None
    if not key:
        return SeedOutcome(datei, None, "error", "Definition hat keinen `key`")

    # Nicht konfigurierbare Platzhalter (Basis-Ticket) → überspringen statt
    # kaputt einspielen.
    offen = {w for _, w in collect_group_refs(roh)
             if _PLACEHOLDER_RE.fullmatch(w) and w not in mapping}
    if offen == {BASIS_TICKET_PLACEHOLDER}:
        return SeedOutcome(datei, key, "skipped",
                           "keine zuständige Gruppe konfiguriert "
                           "(--basis-group / SEED_BASIS_TICKET_GROUP)")

    defn_dict = replace_placeholders(roh, mapping)

    outcome = SeedOutcome(datei, key, "error")
    if rechte is not None:
        defn_dict = backfill.merge_into_definition(defn_dict, rechte.permissions.get(key))

    probleme = check_group_refs(defn_dict, bekannte_ids)
    if probleme:
        outcome.meldung = "Gruppen-Referenzen kaputt – nicht eingespielt: " + "; ".join(probleme)
        logger.error("Seed %s: %s", datei, outcome.meldung)
        return outcome

    for stelle, text in find_stray_placeholders(defn_dict):
        # Kein Abbruch: an dieser Stelle steht keine Gruppen-ID, sondern Text.
        outcome.warnungen.append(f"Platzhalter im Text bei {stelle}: „{text}“")

    try:
        defn = ProcessDefinition.model_validate(defn_dict)
    except Exception as e:
        outcome.meldung = f"validiert nicht gegen ProcessDefinition: {e}"
        logger.error("Seed %s: %s", datei, outcome.meldung)
        return outcome

    vorhanden = defstore.list_versions(key)
    if vorhanden:
        zustaende = ", ".join(f"v{v['version']}/{v['status']}" for v in vorhanden)
        # An diesem Prozess wird NICHTS angefasst; die berechneten Erstellrechte
        # bleiben deshalb bewusst aus dem Bericht (sonst läse es sich, als wären
        # sie gesetzt worden).
        outcome.aktion = "skipped"
        outcome.meldung = f"Schlüssel existiert bereits ({zustaende}) – nichts überschrieben"
        logger.info("Seed %s übersprungen: %s", key, outcome.meldung)
        return outcome

    # Ab hier wird der Prozess (mindestens gedanklich) angelegt – erst jetzt sind
    # die Erstellrechte eine Aussage über den Zielzustand.
    if rechte is not None:
        outcome.create_permissions = defn_dict.get("createPermissions")
        outcome.wirkungslose_gruppen = list(rechte.ineffective_groups.get(key, []))

    if not commit:
        outcome.aktion = "would_create"
        outcome.meldung = "würde angelegt" + (" und veröffentlicht" if publish else " (nur Entwurf)")
        return outcome

    # Exakt wie der Import-Endpunkt serialisieren (api/v1/processes._dump), damit
    # geseedete und importierte Definitionen in der DB identisch aussehen.
    definition_json = json.dumps(defn.model_dump(by_alias=True), ensure_ascii=False)
    try:
        defstore.create_process(key, defn.name, definition_json, actor, actor_name)
        if publish:
            defstore.publish(key, 1)
    except defstore.ProcessKeyExists:
        outcome.aktion = "skipped"
        outcome.meldung = "Schlüssel wurde parallel angelegt – nichts überschrieben"
        return outcome

    outcome.aktion = "created"
    outcome.meldung = "angelegt" + (" und veröffentlicht" if publish else " (Entwurf v1)")
    logger.info("Seed %s: %s", key, outcome.meldung)
    return outcome
