"""
In-App-Benachrichtigungen aus dem Verlauf ableiten – ERGÄNZUNG zur Mail.

Jeder Verlaufs-Eintrag läuft durch `process_events.write`; von dort wird `fanout`
aufgerufen (best-effort, darf nie den eigentlichen Vorgang stören). Der
Mailversand (services/process_actions) bleibt davon völlig unberührt und bewusst
sparsam. In der App darf es großzügiger sein:

| Ereignis                         | Ersteller:in + Beobachter:innen | neu zuständig         |
|----------------------------------|---------------------------------|-----------------------|
| Phase gewechselt / abgeschlossen | progress                        | task („Neue Aufgabe") |
| wieder aufgenommen               | progress                        | task                  |
| zur Nachbesserung zurückgegeben  | progress                        | task                  |
| abgelehnt (auch d. Fachabteilung)| progress                        | –                     |
| Fachabteilung erledigt           | progress                        | –                     |
| Nachtrag                         | addendum (+ Mitglieder der beteiligten Fachabteilungen) |
| als Beobachter:in eingetragen    | watch an die eingetragene Person                        |

Regeln:
- Die handelnde Person bekommt nie eine Meldung über die eigene Aktion.
- Interne Einträge und „Angaben geändert" erzeugen KEINE Meldung – letzteres würde
  verraten, DASS ein (evtl. unsichtbares) Feld geändert wurde (Feld-Sichtbarkeit).
- Texte enthalten keine Feldwerte, nur Auftragstitel, Phase und Abteilung.
- Phasen, die beim Betreten sofort weiterschalten (on_enter-auto_advance mit
  greifendem Guard), erzeugen keine „Neue Aufgabe" – wie beim Mailversand.
- Je Person höchstens EINE Meldung pro Ereignis (task > addendum/watch > progress).

`plan` ist rein (ohne DB) und vollständig testbar; `fanout` sammelt nur die Daten
ein und speichert.
"""
from typing import Callable, Iterable, Optional

from backend.services import process_events as ev
from backend.services import process_runtime as pr
from backend.utils.logger import logger

KIND_TASK = "task"
KIND_PROGRESS = "progress"
KIND_ADDENDUM = "addendum"
KIND_WATCH = "watch"

_PRIORITY = {KIND_TASK: 3, KIND_ADDENDUM: 2, KIND_WATCH: 2, KIND_PROGRESS: 1}

#: Nur diese Aktionen erzeugen Meldungen – alles andere wird ohne DB-Zugriff
#: übersprungen (z. B. das häufige „updated").
RELEVANT_ACTIONS = {
    ev.ADVANCED, ev.REOPENED, ev.APPROVAL_SENT_BACK, ev.REJECTED,
    ev.DEPARTMENT_REJECTED, ev.DEPARTMENT_DONE, ev.ADDENDUM, ev.WATCHER_ADDED,
}


def _title(row: dict) -> str:
    return str(row.get("title") or f"Auftrag #{row.get('id')}")


def _link(row: dict, *, edit: bool = False) -> str:
    base = f"/prozess-auftraege/{row.get('id')}"
    # Aufgaben öffnen wie die Mail direkt die Bearbeitung (Rechte entscheidet der Server).
    return f"{base}?ansicht=bearbeiten" if edit else base


def _phase_label(defn, key: Optional[str]) -> str:
    if defn is not None and key:
        for p in defn.phases:
            if p.key == key:
                return p.label or p.key
    return key or "—"


def _group_name(groups_by_id: dict, gid) -> str:
    g = groups_by_id.get(gid) or {}
    return str(g.get("name") or gid or "—")


def _members(groups_by_id: dict, gids: Iterable) -> set:
    out: set = set()
    for gid in gids:
        out.update(m for m in ((groups_by_id.get(gid) or {}).get("members") or []) if m)
    return out


def responsible_people(defn, row: dict, groups_by_id: dict) -> tuple[set, Optional[str]]:
    """Personen der zuständigen Stelle der AKTUELLEN Phase + Name der Abteilung(en)
    (None bei persönlicher Zuständigkeit). Leer bei abgeschlossenem Auftrag."""
    rt = row.get("runtime") or {}
    if defn is None or pr.is_terminal(rt):
        return set(), None
    phase = pr.current_phase(defn, rt)
    if phase is None:
        return set(), None
    resp = pr.resolve_responsibility(phase, row.get("values") or {})
    kind = resp.get("kind")
    if kind == "owner":
        return ({row["owner_id"]} if row.get("owner_id") else set()), None
    if kind == "user":
        return ({resp["user"]} if resp.get("user") else set()), None
    if kind == "group":
        gid = resp.get("group")
        return (_members(groups_by_id, [gid]) if gid else set()), (_group_name(groups_by_id, gid) if gid else None)
    if kind == "departments":
        live = pr.current_departments(rt)
        gids = ([d.get("group") for d in live if d.get("status") not in ("done", "skipped")]
                if live else [d.get("group") for d in resp.get("departments") or []])
        gids = [g for g in gids if g]
        return _members(groups_by_id, gids), ", ".join(_group_name(groups_by_id, g) for g in gids) or None
    return set(), None


def plan(action: str, row: dict, *, defn, details: Optional[dict], body: Optional[str],
         actor_id: Optional[str], actor_name: Optional[str], internal: bool,
         watchers: Iterable[str], groups_by_id: dict,
         auto_pending: Callable = lambda phase: False) -> list[dict]:
    """Meldungen für EIN Verlaufs-Ereignis (rein, ohne DB). Rückgabe:
    [{user_id, ticket_id, kind, title, body, link, actor_name}]."""
    if internal or action not in RELEVANT_ACTIONS:
        return []
    details = details or {}
    out: dict = {}

    def add(users: Iterable, kind: str, text: str, *, edit: bool = False) -> None:
        for u in users:
            if not u or u == actor_id:
                continue
            cur = out.get(u)
            if cur and _PRIORITY[cur["kind"]] >= _PRIORITY[kind]:
                continue
            out[u] = {"user_id": u, "ticket_id": row.get("id"), "kind": kind,
                      "title": _title(row), "body": text, "link": _link(row, edit=edit),
                      "actor_name": actor_name}

    beteiligte = ({row.get("owner_id")} | set(watchers or [])) - {None, ""}
    rt = row.get("runtime") or {}
    cur_phase = pr.current_phase(defn, rt) if defn is not None else None
    cur_label = _phase_label(defn, cur_phase.key if cur_phase else None)

    def task(text: str) -> None:
        if cur_phase is None or auto_pending(cur_phase):
            return   # Durchgangsphase: nichts zu tun für die Stelle (wie beim Mailversand)
        people, abteilung = responsible_people(defn, row, groups_by_id)
        add(people, KIND_TASK, f"{text}{f' ({abteilung})' if abteilung else ''}", edit=True)

    if action == ev.ADVANCED:
        status = details.get("status") or row.get("status")
        if status in ("archived", "rejected") or pr.is_terminal(rt) or not details.get("to_phase"):
            add(beteiligte, KIND_PROGRESS, "Abgeschlossen")
        else:
            task(f"Neue Aufgabe: Phase „{cur_label}“")
            add(beteiligte, KIND_PROGRESS, f"Weiter in Phase „{_phase_label(defn, details.get('to_phase'))}“")
    elif action == ev.REOPENED:
        task(f"Wieder aufgenommen – Phase „{cur_label}“")
        add(beteiligte, KIND_PROGRESS, f"Wieder aufgenommen – Phase „{cur_label}“")
    elif action == ev.APPROVAL_SENT_BACK:
        task(f"Nachbesserung nötig – Phase „{cur_label}“")
        add(beteiligte, KIND_PROGRESS, f"Zur Nachbesserung zurückgegeben – Phase „{cur_label}“")
    elif action == ev.REJECTED:
        add(beteiligte, KIND_PROGRESS, "Abgelehnt")
    elif action == ev.DEPARTMENT_REJECTED:
        add(beteiligte, KIND_PROGRESS, f"Abgelehnt durch {_group_name(groups_by_id, details.get('group'))}")
    elif action == ev.DEPARTMENT_DONE:
        add(beteiligte, KIND_PROGRESS, f"{_group_name(groups_by_id, details.get('group'))} hat ihren Teil erledigt")
    elif action == ev.ADDENDUM:
        vorschau = " ".join(str(body or "").split())
        vorschau = (vorschau[:140] + "…") if len(vorschau) > 140 else vorschau
        abteilungen = pr.involved_department_group_ids(defn, rt) if defn is not None else set()
        add(beteiligte | _members(groups_by_id, abteilungen), KIND_ADDENDUM,
            f"Nachtrag: {vorschau}" if vorschau else "Neuer Nachtrag")
    elif action == ev.WATCHER_ADDED:
        add([details.get("watcher")], KIND_WATCH,
            f"{actor_name or 'Jemand'} hat dich als Beobachter:in eingetragen")
    return list(out.values())


# ── Hülle: Daten einsammeln + speichern ────────────────────────────────────────

_DEFN_CACHE: dict = {}


def _load_defn(row: dict):
    """Gepinnte Definition (unveränderlich je key+version → prozessweit cachebar)."""
    pin = (row.get("process_key"), row.get("process_version"))
    if pin in _DEFN_CACHE:
        return _DEFN_CACHE[pin]
    from backend.database import process_definitions as defstore
    from backend.schemas.process_definition import ProcessDefinition
    d = defstore.get_definition(*pin)
    defn = ProcessDefinition.model_validate(d["definition"]) if d and d.get("definition") else None
    if len(_DEFN_CACHE) > 128:
        _DEFN_CACHE.clear()
    _DEFN_CACHE[pin] = defn
    return defn


def fanout(row: dict, action: str, *, actor_id: Optional[str], actor_name: Optional[str],
           details: Optional[dict] = None, body: Optional[str] = None,
           internal: bool = False) -> int:
    """Meldungen zu einem Verlaufs-Ereignis erzeugen und speichern. Gibt die Zahl
    der benachrichtigten Personen zurück. Fehler steigen auf – der Aufrufer
    (process_events) fängt sie ab, damit nie ein Vorgang daran scheitert."""
    if internal or action not in RELEVANT_ACTIONS or not row.get("id"):
        return 0
    from backend.database import process_ticket_watchers as watchers_db
    from backend.database import user_notifications as store
    from backend.database.groups import get_groups
    from backend.services import process_engine as engine

    defn = _load_defn(row)
    try:
        watchers = watchers_db.watcher_ids(int(row["id"]))
    except Exception:
        logger.warning("Beobachter für #%s nicht ladbar – Meldungen ohne sie", row.get("id"))
        watchers = set()
    groups_by_id = {g.get("id"): g for g in (get_groups() or [])}
    items = plan(action, row, defn=defn, details=details, body=body, actor_id=actor_id,
                 actor_name=actor_name, internal=internal, watchers=watchers,
                 groups_by_id=groups_by_id,
                 auto_pending=lambda phase: engine._auto_advance_pending(defn, phase, row))
    return store.add_many(items) if items else 0
