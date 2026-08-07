"""
Feldbezogene Sichtbarkeit + Schreibschutz für definitions-getriebene Tickets (§5).

Modell (Sichtbarkeit liegt IM Feld):
  - `confidential` + `visibleToGroups`: HARTES Gate. Auch Vollsicht sieht das Feld
    NICHT, außer als Mitglied einer der Gruppen – oder per Admin-Fallback.
  - nicht-confidential ohne `visibleToGroups`: geteiltes Feld, für alle Beteiligten.
  - nicht-confidential MIT `visibleToGroups`: nur diese Gruppen ODER Vollsicht.

Enforcement-Invariante (§5.1): JEDER wertetragende Ausgabekanal passiert diesen
Filter. Im neuen System ist das ausschließlich `values` – der Runtime-Zustand
trägt per Konstruktion keine Feldwerte (§5.6), History existiert (noch) nicht.

Alle Kern-Funktionen sind rein (kein DB-Zugriff) → unit-testbar. Nur
`build_viewer_ctx` liest Gruppenmitgliedschaften aus der DB.
"""
from dataclasses import dataclass, field as dc_field
from typing import Optional

from backend.schemas.process_definition import ProcessDefinition, PhaseDef, FieldDef, FieldMode
from backend.services import process_runtime as pr
from backend.services.condition_dsl import evaluate


@dataclass
class ViewerCtx:
    full_view: bool = False
    is_admin: bool = False
    group_ids: set = dc_field(default_factory=set)


# ── reine Sichtbarkeits-Logik ─────────────────────────────────────────────────

def can_see_field(f: FieldDef, ctx: ViewerCtx) -> bool:
    vis = f.visibility
    confidential = bool(vis and vis.confidential)
    groups = set(vis.visibleToGroups) if vis else set()
    if confidential:
        # Hartes Gate: nur Gruppenmitglieder – Vollsicht hilft NICHT; Admin-Fallback.
        return ctx.is_admin or bool(ctx.group_ids & groups)
    if not groups:
        return True                          # geteiltes Feld
    return ctx.full_view or bool(ctx.group_ids & groups)


def _effective_can_see(f: FieldDef, ctx: ViewerCtx, fmap: dict, _seen: Optional[set] = None) -> bool:
    """Sichtbarkeit inkl. Quelle: ein computed-Feld ist nur sichtbar, wenn der
    Betrachter AUCH sein Quellfeld sehen darf – sonst würde ein Spiegelfeld einen
    vertraulichen Wert offenlegen (§5, hartes Gate darf nicht umgangen werden)."""
    if not can_see_field(f, ctx):
        return False
    if f.computed:
        _seen = _seen or set()
        if f.key in _seen:
            return True                       # Zyklus-Schutz
        _seen.add(f.key)
        src = fmap.get(f.computed.from_)
        if src is not None and not _effective_can_see(src, ctx, fmap, _seen):
            return False
    return True


def visible_field_keys(defn: Optional[ProcessDefinition], ctx: ViewerCtx) -> set:
    if defn is None:
        return set()                          # default-deny
    fmap = {f.key: f for f in defn.fields}
    return {f.key for f in defn.fields if _effective_can_see(f, ctx, fmap)}


def filter_values(defn: Optional[ProcessDefinition], values: dict, ctx: ViewerCtx) -> dict:
    """Gibt nur die für den Betrachter sichtbaren Feldwerte zurück (default-deny)."""
    if defn is None or not values:
        return {}
    allowed = visible_field_keys(defn, ctx)
    return {k: v for k, v in values.items() if k in allowed}


def editable_field_keys(defn: ProcessDefinition, phase: PhaseDef, ctx: ViewerCtx,
                        values: dict) -> set:
    """Felder, die dieser Betrachter in DIESER Phase schreiben darf:
    editable/append_only-Modus UND sichtbar (inkl. Quelle) UND (kein visibleWhen
    oder erfüllt gegen `values`)."""
    fmap = {f.key: f for f in defn.fields}
    out = set()
    for fr in phase.fields:
        if fr.mode not in (FieldMode.editable, FieldMode.append_only):
            continue
        f = fmap.get(fr.ref)
        if f is None or not _effective_can_see(f, ctx, fmap):
            continue
        if fr.visibleWhen is not None and not evaluate(fr.visibleWhen, values):
            continue
        out.add(fr.ref)
    return out


def writable_keys(defn: ProcessDefinition, phase: PhaseDef, ctx: ViewerCtx,
                  stored: dict, submitted: dict) -> set:
    """Schreibbare Felder – wie editable_field_keys, aber visibleWhen wird gegen
    einen SICHEREN Kontext ausgewertet: gespeicherte Werte + nur solche gesendeten
    Felder, deren FieldRef in dieser Phase selbst editierbar ist. So kann ein
    Aufrufer NICHT über ein nicht-editierbares (readonly/hidden) Feld im Body ein
    anderes, per visibleWhen gesperrtes Feld freischalten."""
    editable_refs = {fr.ref for fr in phase.fields
                     if fr.mode in (FieldMode.editable, FieldMode.append_only)}
    eval_values = {**stored, **{k: v for k, v in submitted.items() if k in editable_refs}}
    return editable_field_keys(defn, phase, ctx, eval_values)


def apply_writes(defn: ProcessDefinition, phase: PhaseDef, stored: dict,
                 submitted: dict, ctx: ViewerCtx) -> dict:
    """Schreibschutz-Merge: Basis = gespeicherte Werte; nur erlaubte (sichtbare +
    in dieser Phase editierbare) Felder werden übernommen, der Rest verworfen.
    Verborgene Felder behalten immer ihren Bestandswert."""
    merged = dict(stored)
    allowed = writable_keys(defn, phase, ctx, stored, submitted)
    for k, v in submitted.items():
        if k in allowed:
            merged[k] = v
    return merged


# ── Betrachter-Kontext (DB: Gruppenmitgliedschaft) ────────────────────────────

def build_viewer_ctx(user: dict, ticket_row: dict, defn: Optional[ProcessDefinition]) -> ViewerCtx:
    from backend.database.users import PERM_VIEW, PERM_MANAGE, PERM_ADMIN
    from backend.database.groups import get_group_ids_for_user

    perms = set(user.get("permissions") or [])
    is_admin = PERM_ADMIN in perms
    oversight = bool(perms & {PERM_VIEW, PERM_MANAGE, PERM_ADMIN})
    uid = user.get("id")
    # Fail-restriktiv: kann die Mitgliedschaft nicht geladen werden, gilt „keine
    # Gruppen“ (= weniger Sicht), nie mehr. Loggen statt durchreichen.
    group_ids: set = set()
    if uid:
        try:
            group_ids = set(get_group_ids_for_user(uid))
        except Exception:
            from backend.utils.logger import logger
            logger.warning("Gruppen-Mitgliedschaft für %s nicht ladbar – fail-restriktiv", uid)
    is_owner = ticket_row.get("owner_id") == uid and uid is not None
    terminal = (ticket_row.get("status") in ("archived", "rejected")
                or bool((ticket_row.get("runtime") or {}).get("rejected")))

    full_view = oversight or is_owner
    if not full_view and not terminal and defn is not None:
        phase = pr.current_phase(defn, ticket_row.get("runtime") or {})
        if phase is not None and phase.grantsFullView and \
                _is_responsible(phase, ticket_row, uid, group_ids):
            full_view = True
    return ViewerCtx(full_view=full_view, is_admin=is_admin, group_ids=group_ids)


def _is_responsible(phase: PhaseDef, ticket_row: dict, uid, group_ids: set) -> bool:
    resp = pr.resolve_responsibility(phase, ticket_row.get("values") or {})
    kind = resp.get("kind")
    if kind == "owner":
        return ticket_row.get("owner_id") == uid
    if kind == "group":
        return resp.get("group") in group_ids
    if kind == "user":
        return resp.get("user") == uid
    if kind == "departments":
        return any(d["group"] in group_ids for d in resp.get("departments", []))
    return False
