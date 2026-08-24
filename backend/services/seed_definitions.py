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

Daneben steht in diesem Modul die Pflege der **System-Prozesse**
(`ensure_system_processes`): die gehören zum Produkt, nicht zur Konfiguration
einer Installation, entstehen beim Start automatisch und sind in der Oberfläche
nicht änderbar. Der Seeder-Lauf oben lässt sie deshalb aus – es gibt genau einen
Weg, wie sie in die Datenbank kommen.
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

#: Gruppen, die ausschließlich automatisch über eine Phase zugewiesen werden
#: (responsibility.kind=group) und deshalb in Auswahl-Dropdowns nichts zu
#: suchen haben. Entspricht `workflow_state.assign_group_names()` des
#: Alt-Systems – nur bei NEUANLAGE gesetzt, ein Admin kann es ändern.
AUTO_ASSIGNED_GROUP_NAMES: list[str] = ["Sekretariat GL", "FreigabeHerrLutz", "Reisestelle"]

#: Prozesse, die zum PRODUKT gehören und nicht zur Konfiguration einer
#: Installation. Folgen (beide serverseitig erzwungen, nicht nur in der
#: Oberfläche): sie entstehen beim Start automatisch (ensure_system_processes)
#: und sind nicht änderbar – die API antwortet auf jede Mutation mit
#: SYSTEM_PROCESS_READONLY. Aufnahme ist eine Produkt-Entscheidung: ein Prozess
#: darf nur hier stehen, wenn er selbsttragend ist (siehe
#: ensure_system_processes).
SYSTEM_PROCESS_KEYS = frozenset({"basis-ticket"})

#: Wer die automatisch gepflegten Versionen angelegt hat. Steht so in
#: created_by/created_by_name – in der Versionsliste soll erkennbar sein, dass
#: hier niemand von Hand gearbeitet hat.
SYSTEM_ACTOR = "system"
SYSTEM_ACTOR_NAME = "System (Auslieferung)"

#: Erkennt einen Platzhalter, der (noch) nicht aufgelöst ist.
_PLACEHOLDER_RE = re.compile(r"HIER_[A-Z0-9_]*_EINSETZEN")

#: Kennzeichnung im Trockenlauf für Gruppen, die es noch nicht gibt. Muss keine
#: echte ID sein – im Trockenlauf wird nichts geschrieben, geprüft wird nur die
#: Struktur.
_DRY_RUN_ID_PREFIX = "DRYRUN-NEUE-GRUPPE:"


def is_system_process(key: Optional[str]) -> bool:
    """Gehört dieser Schlüssel zu einem System-Prozess?

    Aus dem Schlüssel abgeleitet und NICHT in der Datenbank vermerkt: welche
    Prozesse zum Produkt gehören, entscheidet der Code. Ein DB-Feld könnte man
    umsetzen und hätte damit einen änderbaren „unveränderlichen" Prozess.
    """
    return bool(key) and key in SYSTEM_PROCESS_KEYS


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


def unresolved_placeholders(defn: dict) -> list[tuple[str, str]]:
    """NUR die unaufgelösten Platzhalter (Pfad, Platzhalter) – für den manuellen
    Import: unbekannte echte Gruppen-IDs sind dort erlaubt (der Entwurf wird im
    Editor repariert), ein stehen gebliebener Platzhalter aber nie."""
    return [(pfad, wert) for pfad, wert in collect_group_refs(defn)
            if _PLACEHOLDER_RE.fullmatch(wert)]


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


def build_placeholder_mapping(index: dict[str, str]) -> dict[str, str]:
    """Platzhalter → echte Gruppen-ID. Nicht auflösbare Platzhalter fehlen in der
    Abbildung (und fliegen später in der Fail-closed-Prüfung auf)."""
    mapping: dict[str, str] = {}
    for ph, name in PLACEHOLDER_GROUP_NAMES.items():
        gid = index.get(name.strip().lower())
        if gid:
            mapping[ph] = gid
    return mapping


def seed_processes(*, commit: bool = False,
                   with_permissions: bool = True,
                   publish: bool = True,
                   only: Optional[set[str]] = None,
                   actor: str = "seed_processes",
                   actor_name: str = "Seeder") -> SeedReport:
    """Spielt die ausgelieferten Prozesse ein.

    `commit=False` (Standard) schreibt NICHTS – weder Prozesse noch Gruppen.
    """
    report = SeedReport(commit=commit)

    # 1. Gruppen. Fehlende Pflichtgruppen entstehen nur mit `commit`; im
    #    Trockenlauf treten Ersatz-IDs an ihre Stelle (siehe unten).
    vorher = build_group_index(groupsdb.get_groups())
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

    mapping = build_placeholder_mapping(index)
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

    if is_system_process(key):
        # System-Prozesse pflegt `ensure_system_processes` bei jedem Start. Ein
        # zweiter Weg in die DB könnte nur abweichen – und weil dieser Lauf
        # vorhandene Schlüssel überspringt, wäre er ohnehin wirkungslos. Also
        # ausdrücklich sagen, dass hier nichts zu tun ist.
        return SeedOutcome(datei, key, "skipped",
                           "System-Prozess – wird beim Start automatisch angelegt und "
                           "aktuell gehalten, dieser Lauf fasst ihn nicht an")

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


# ── System-Prozesse: beim Start sicherstellen ────────────────────────────────

@dataclass
class SystemProcessOutcome:
    """Was mit EINEM System-Prozess beim Start passiert ist."""
    key: str
    aktion: str                    # created | updated | unchanged | error
    meldung: str = ""
    version: Optional[int] = None


def system_seed_path(key: str) -> Optional[Path]:
    """Die ausgelieferte JSON eines System-Prozesses.

    Erst über die Namenskonvention (`prozess-<key>.json`), dann über den Inhalt.
    Die Konvention zuerst, weil die Inhaltssuche jede Seed-Datei parsen muss: eine
    kaputte Nachbardatei würde sonst die Datei verdecken, um die es geht, und der
    Startlauf meldete „keine ausgelieferte Definition" statt „nicht lesbar".
    """
    dateien = process_seed_files()
    for pfad in dateien:
        if pfad.stem == f"prozess-{key}":
            return pfad
    for pfad in dateien:
        try:
            if json.loads(pfad.read_text(encoding="utf-8")).get("key") == key:
                return pfad
        except Exception:
            continue        # kaputte Datei verdeckt die Suche nicht
    return None


def _vergleichsform(defn: Any) -> str:
    """Kanonische Vergleichsform einer Definition.

    Sortierte Schlüssel und keine Formatierung: verglichen wird der INHALT.
    Sonst legte jeder Start eine neue Version an, sobald jemand die
    ausgelieferte JSON umformatiert oder ein Feld verschiebt.

    Vor dem Vergleich läuft die Definition durch das Schema, damit Standardwerte
    gefüllt sind – die Fassung in der DB kann von einer Schema-Version stammen,
    die ein heute optionales Feld noch nicht kannte. Validiert sie nicht, wird sie
    unverändert verglichen (dann weicht sie ab und wird ersetzt, was richtig ist).
    """
    if not isinstance(defn, dict):
        return ""
    try:
        defn = ProcessDefinition.model_validate(defn).model_dump(by_alias=True)
    except Exception:
        pass
    return json.dumps(defn, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def ensure_system_processes(*, keys: Optional[Iterable[str]] = None) -> list[SystemProcessOutcome]:
    """System-Prozesse beim Start anlegen bzw. aktuell halten.

    WARUM das hier automatisch geht und für die übrigen neun Prozesse NICHT –
    bitte vor dem Erweitern von SYSTEM_PROCESS_KEYS lesen:

    Das Basis-Ticket ist SELBSTTRAGEND. Es enthält keinen `HIER_`-Platzhalter und
    keine Gruppe in einer Phase (die Zuständigkeit steht in einem Feld mit
    `widget=group` und wird beim Anlegen gewählt), und
    `createPermissions.everyone` ist wahr. Es braucht damit weder eine
    Gruppen-Auflösung noch Alt-Daten und ist ab dem ersten Start für jede:n
    anlegbar. Die anderen neun sind es nicht: sie brauchen Fachabteilungen mit
    Verteiler-Adressen und die Übernahme der Erstellrechte. Automatisch
    veröffentlicht sähen sie fertig aus, wären aber nur für Admins anlegbar und
    schickten Mails an leere Verteiler. Deshalb bleiben sie beim Admin-Knopf
    (`POST /processes:seed`), und hier steht nur, was ohne Konfiguration
    funktioniert.

    Ein Update ist eine NEUE VERSION, kein Überschreiben: Definitionen sind
    unveränderlich und Aufträge pinnen ihre Version – die alte muss lesbar
    bleiben, sonst verlieren laufende Aufträge ihre Definition.

    Wirft nicht: je Prozess wird der Fehlschlag als Warnung protokolliert und im
    Ergebnis vermerkt. Der Start darf daran nicht scheitern.
    """
    ergebnisse: list[SystemProcessOutcome] = []
    for key in sorted(keys if keys is not None else SYSTEM_PROCESS_KEYS):
        try:
            ergebnisse.append(_ensure_system_process(key))
        except Exception as e:
            logger.warning("System-Prozess %s nicht sichergestellt: %s: %s",
                           key, type(e).__name__, e)
            ergebnisse.append(SystemProcessOutcome(key, "error", f"{type(e).__name__}: {e}"))
    return ergebnisse


def _ensure_system_process(key: str) -> SystemProcessOutcome:
    pfad = system_seed_path(key)
    if pfad is None:
        raise SeedError(f"keine ausgelieferte Definition für „{key}“ gefunden")
    roh = _lade_seed(pfad)          # kaputte JSON → Ausnahme → Warnung, kein Abbruch

    # Fail-closed wie im Seeder-Lauf, nur strenger: ein System-Prozess muss OHNE
    # Gruppen-Auflösung einspielbar sein. Steht doch eine Gruppen-ID oder ein
    # Platzhalter darin, ist er nicht mehr selbsttragend (die IDs sind pro
    # Installation verschieden) – dann lieber nichts einspielen als etwas
    # dauerhaft Kaputtes. Die leere Menge bekannter IDs ist genau diese Aussage.
    probleme = check_group_refs(roh, set())
    if probleme:
        raise SeedError("verweist auf Gruppen und ist damit nicht selbsttragend – "
                        "gehört nicht in SYSTEM_PROCESS_KEYS: " + "; ".join(probleme))

    defn = ProcessDefinition.model_validate(roh)
    # Exakt wie Seeder und Import-Endpunkt serialisieren, damit die Definitionen
    # in der DB auf jedem Weg identisch aussehen.
    definition_json = json.dumps(defn.model_dump(by_alias=True), ensure_ascii=False)
    soll = _vergleichsform(defn.model_dump(by_alias=True))

    versionen = defstore.list_versions(key)
    if not versionen:
        defstore.create_process(key, defn.name, definition_json,
                                SYSTEM_ACTOR, SYSTEM_ACTOR_NAME)
        defstore.publish(key, 1)
        logger.info("System-Prozess %s angelegt und veröffentlicht (v1)", key)
        return SystemProcessOutcome(key, "created", "angelegt und veröffentlicht", 1)

    veroeffentlicht = defstore.get_published(key)
    if veroeffentlicht and _vergleichsform(veroeffentlicht.get("definition")) == soll:
        return SystemProcessOutcome(key, "unchanged", "unverändert",
                                    int(veroeffentlicht["version"]))

    # Ziel ist ein Entwurf: ein offener wird benutzt (den kann nur ein
    # abgebrochener Lauf hinterlassen – über die API ist der Prozess nicht
    # änderbar), sonst wird die veröffentlichte Version als neue Version geklont.
    entwurf = next((v for v in versionen if v.get("status") == "draft"), None)
    if entwurf is None:
        if not veroeffentlicht:
            raise SeedError(
                f"„{key}“ hat Versionen, aber keine veröffentlichte und keinen Entwurf "
                f"({', '.join('v%s/%s' % (v['version'], v['status']) for v in versionen)}) "
                "– das muss von Hand geprüft werden")
        entwurf = defstore.create_or_get_draft(key, SYSTEM_ACTOR, SYSTEM_ACTOR_NAME)
    ziel = int(entwurf["version"])

    defstore.update_draft(key, ziel, defn.name, definition_json)
    defstore.publish(key, ziel)

    if veroeffentlicht:
        meldung = (f"ausgelieferte Definition weicht von v{veroeffentlicht['version']} ab "
                   f"– v{ziel} veröffentlicht (alte Version bleibt für laufende Aufträge)")
        aktion = "updated"
    else:
        meldung = f"keine veröffentlichte Version vorhanden – v{ziel} veröffentlicht"
        aktion = "created"
    logger.info("System-Prozess %s: %s", key, meldung)
    return SystemProcessOutcome(key, aktion, meldung, ziel)
