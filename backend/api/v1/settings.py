import re
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, Request, Query, Response, UploadFile
from pydantic import BaseModel
from typing import Optional

from backend.core.dependencies import get_current_user
from backend.database.groups import get_groups, save_groups
from backend.database.settings import (
    get_companies, get_companies_full, set_companies_full,
    get_process_order, set_process_order, template_source_company,
    get_template_labels, get_template_label, set_template_labels,
    set_template_label_baseline,
)
from backend.database import company_templates as ctpl_db
from backend.services import attachment_storage as storage
from backend.services import template_format
from backend.database.users import (
    list_users, set_user_role, get_user,
    add_extra_permission, remove_extra_permission, set_extra_permissions,
    VALID_ROLES, PERM_ADMIN,
)
from backend.database.audit_log import record_audit, list_audit, distinct_actions
from backend.schemas.responses import DataResponse
from backend.services.microsoft_mail import send_test_mail
from backend.utils.config import config
from backend.utils.logger import logger

router = APIRouter()

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Auth helper ───────────────────────────────────────────────────────────────

def require_admin(user: dict) -> None:
    if PERM_ADMIN not in user.get("permissions", []):
        raise HTTPException(403, "Admin-Rechte erforderlich")


def _audit(user: dict, action: str, **kw) -> None:
    """Kurzform für record_audit mit ausgefülltem Actor (aktueller Admin)."""
    record_audit(
        action=action,
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        **kw,
    )


# ── Diff-Helfer fürs Audit (Bulk-Speichern schickt alles → nur echte Änderungen loggen) ──

def _names_from(request) -> dict:
    return {u["id"]: (u.get("displayName") or u.get("mail") or u["id"])
            for u in getattr(request.app.state, "user_cache", [])}


def _summary(parts: list[str], noun: str) -> str:
    return parts[0] if len(parts) == 1 else f"{len(parts)} Änderungen an {noun}"


# ── Pflicht-Fachabteilungen ───────────────────────────────────────────────────
#
# Namensquelle ist `services/seed_definitions.py` (dieselbe Liste, aus der die
# ausgelieferten Prozesse ihre Platzhalter auflösen). Der Schutz hängt bewusst am
# NAMEN und nicht an der ID: der Seeder findet die Gruppe über den Namen. Wird
# eine Pflichtgruppe umbenannt, legt der nächste Lauf eine zweite – leere –
# Gruppe an, und die Zuständigen des Prozesses stehen in der falschen.
#
# Die ID-Seite deckt `_assert_groups_unreferenced` ab (Referenzen aus
# veröffentlichten UND archivierten Definitionen). Beides ist nötig: eine vom
# Admin selbst angelegte Fachabteilung steht in keiner Namensliste, wird aber
# von einer Definition referenziert.

def _required_group_names() -> set[str]:
    """Pflicht-Namen, kleingeschrieben und getrimmt (Vergleich ist case-insensitiv,
    weil eine Gruppe in der DB „IT" oder „it" heißen kann)."""
    from backend.services.seed_definitions import required_group_names
    return {(n or "").strip().lower() for n in required_group_names() if (n or "").strip()}


def _is_required_group_name(name: str) -> bool:
    """True, wenn eine Gruppe mit diesem Namen für die Prozesse existieren muss."""
    if not name:
        return False
    return name.strip().lower() in _required_group_names()


def _referenced_group_ids(group_ids: set) -> set:
    """Teilmenge der IDs, die von irgendeiner Prozess-Definition referenziert wird.

    Nur für die ANZEIGE (`GroupOut.required`) – deshalb hier fail-OPEN: schlägt die
    Abfrage fehl, fehlt höchstens ein Schloss-Symbol. Das tatsächliche Löschen
    bleibt über `_assert_groups_unreferenced` fail-closed geschützt.
    """
    if not group_ids:
        return set()
    from backend.database import process_definitions as _pdefs
    try:
        return _pdefs.groups_referenced_in_definitions(set(group_ids))
    except Exception:
        logger.warning("Prozess-Referenzen für die Gruppen-Anzeige nicht ladbar")
        return set()


def _assert_groups_unreferenced(group_ids: set) -> None:
    """Von einer Prozess-Definition referenzierte Fachabteilungen (Feld-Sichtbarkeit,
    Zuständigkeit, Automation-Empfänger) dürfen NICHT gelöscht werden – sonst
    würden vertrauliche Felder gepinnter Tickets dauerhaft unlesbar (§5.4).

    FAIL-CLOSED: Kann die Prüfung nicht durchgeführt werden, wird das Löschen
    abgelehnt – ein Prüf-Fehler darf nicht wie „nicht referenziert" wirken."""
    if not group_ids:
        return
    from backend.database import process_definitions as _pdefs
    try:
        referenced = _pdefs.groups_referenced_in_definitions(set(group_ids))
    except Exception:
        logger.exception("Prozess-Referenzprüfung für Gruppen fehlgeschlagen – Löschen abgelehnt")
        raise HTTPException(
            503, "Die Prüfung auf Prozess-Verwendung ist fehlgeschlagen. "
                 "Löschen wurde sicherheitshalber abgelehnt.")
    if referenced:
        raise HTTPException(
            409, "Diese Fachabteilung wird von einem Prozess (Sichtbarkeit, Zuständigkeit "
                 "oder Benachrichtigung) verwendet und kann nicht gelöscht werden.")


def _diff_groups(old_list, new_list, name_of):
    old_by = {g.get("id"): g for g in old_list}
    new_by = {g.get("id"): g for g in new_list}
    created = [g["name"] for g in new_list if g.get("id") not in old_by]
    deleted = [g["name"] for g in old_list if g.get("id") not in new_by]
    modified = []
    for gid, ng in new_by.items():
        og = old_by.get(gid)
        if not og:
            continue
        changes: list[str] = []
        if (og.get("name") or "") != (ng.get("name") or ""):
            changes.append(f"umbenannt: „{og.get('name')}“ → „{ng.get('name')}“")
        om, nm = set(og.get("members", [])), set(ng.get("members", []))
        if nm - om: changes.append("Mitglied +: " + ", ".join(sorted(name_of(m) for m in nm - om)))
        if om - nm: changes.append("Mitglied −: " + ", ".join(sorted(name_of(m) for m in om - nm)))
        od, nd = set(og.get("distributions", [])), set(ng.get("distributions", []))
        if nd - od: changes.append("Verteiler +: " + ", ".join(sorted(nd - od)))
        if od - nd: changes.append("Verteiler −: " + ", ".join(sorted(od - nd)))
        if bool(og.get("hidden")) != bool(ng.get("hidden")):
            changes.append("versteckt: " + ("an" if ng.get("hidden") else "aus"))
        if changes:
            modified.append({"name": ng.get("name"), "changes": changes})
    return created, deleted, modified


def _diff_companies(old_list, new_list):
    old_by = {c["name"]: c for c in old_list}
    new_by = {c["name"]: c for c in new_list}
    created = [n for n in new_by if n not in old_by]
    deleted = [n for n in old_by if n not in new_by]
    modified = []
    fields = [("pnr_from", "Von"), ("pnr_to", "Bis"), ("mandant", "Mandant"),
              ("pnr_shared_with", "geteilt mit"), ("directus_firma_id", "alphacore-Firmen-ID"),
              ("documents_shared_with", "Vorlagen von")]
    for name, nc in new_by.items():
        oc = old_by.get(name)
        if not oc:
            continue
        changes = [f"{label}: {oc.get(k) or '—'} → {nc.get(k) or '—'}"
                   for k, label in fields if (oc.get(k) or None) != (nc.get(k) or None)]
        if changes:
            modified.append({"name": name, "changes": changes})
    return created, deleted, modified


# ── Schemas ───────────────────────────────────────────────────────────────────

class AppUserOut(BaseModel):
    user_id: str
    display_name: str
    email: str
    role: str
    permissions: list[str]
    last_login: str


class SetRoleIn(BaseModel):
    role: str


class SetPermissionsIn(BaseModel):
    permissions: list[str]


class AddRemovePermissionIn(BaseModel):
    permission: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_out(u) -> AppUserOut:
    return AppUserOut(
        user_id=u.user_id,
        display_name=u.display_name,
        email=u.email,
        role=u.role,
        permissions=u.permissions,
        last_login=u.last_login,
    )


def _get_user_or_404(user_id: str):
    u = get_user(user_id)
    if not u:
        raise HTTPException(404, "User nicht gefunden")
    return u


# ── App Users ─────────────────────────────────────────────────────────────────

@router.get("/settings/app-users", response_model=DataResponse[list[AppUserOut]])
def get_app_users(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=[_user_out(u) for u in list_users()])


@router.patch("/settings/app-users/{user_id}/role", response_model=DataResponse[AppUserOut])
def update_user_role(
    user_id: str,
    payload: SetRoleIn,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    if payload.role not in VALID_ROLES:
        raise HTTPException(400, f"Ungültige Rolle. Erlaubt: {', '.join(VALID_ROLES)}")
    result = _user_out(set_user_role(user_id, payload.role))
    _audit(user, "user_role_changed", entity_type="user", entity_id=user_id,
           summary=f"{result.display_name}: Rolle → {payload.role}", details={"role": payload.role})
    return DataResponse(data=result)


# ── User Permissions ──────────────────────────────────────────────────────────

@router.get("/settings/app-users/{user_id}/permissions", response_model=DataResponse[list[str]])
def get_user_permissions(
    user_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    return DataResponse(data=_get_user_or_404(user_id).permissions)


@router.put("/settings/app-users/{user_id}/permissions", response_model=DataResponse[AppUserOut])
def set_user_permissions(
    user_id: str,
    payload: SetPermissionsIn,
    user: dict = Depends(get_current_user),
):
    """Ersetzt extra_permissions komplett."""
    require_admin(user)
    u = _get_user_or_404(user_id)
    # Nur extra_permissions setzen – Rollen-Permissions bleiben implizit erhalten
    role_perms = set(u.permissions) - set(u.extra_permissions)
    new_extras = [p for p in payload.permissions if p not in role_perms]
    set_extra_permissions(user_id, new_extras)
    _audit(user, "user_permissions_set", entity_type="user", entity_id=user_id,
           summary=f"{u.display_name}: Rechte gesetzt", details={"permissions": new_extras})
    return DataResponse(data=_user_out(_get_user_or_404(user_id)))


@router.patch("/settings/app-users/{user_id}/permissions/add", response_model=DataResponse[AppUserOut])
def add_user_permission(
    user_id: str,
    payload: AddRemovePermissionIn,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    _get_user_or_404(user_id)
    _audit(user, "user_permission_added", entity_type="user", entity_id=user_id,
           details={"permission": payload.permission})
    return DataResponse(data=_user_out(add_extra_permission(user_id, payload.permission)))


@router.patch("/settings/app-users/{user_id}/permissions/remove", response_model=DataResponse[AppUserOut])
def remove_user_permission(
    user_id: str,
    payload: AddRemovePermissionIn,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    _get_user_or_404(user_id)
    _audit(user, "user_permission_removed", entity_type="user", entity_id=user_id,
           details={"permission": payload.permission})
    return DataResponse(data=_user_out(remove_extra_permission(user_id, payload.permission)))


# ── ENV / Config ──────────────────────────────────────────────────────────────

class EnvResponse(BaseModel):
    general: dict
    microsoft: dict
    session: dict


@router.get("/settings/env", response_model=DataResponse[EnvResponse])
def get_env(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=EnvResponse(
        general={
            "APP_ENV":     {"value": config.APP_ENV,           "sensitive": False},
            "PORT":        {"value": config.PORT,              "sensitive": False},
            "HTTPS":       {"value": bool(config.HTTPS),       "sensitive": False},
            "TICKET_MAIL": {"value": config.TICKET_MAIL or "—","sensitive": False},
        },
        microsoft={
            "CLIENT_ID":      {"is_set": bool(config.CLIENT_ID),     "sensitive": True},
            "CLIENT_SECRET":  {"is_set": bool(config.CLIENT_SECRET), "sensitive": True},
            "TENANT_ID":      {"is_set": bool(config.TENANT_ID),     "sensitive": True},
            "REDIRECT_URI":   {"value": config.REDIRECT_URI or "—",  "sensitive": False},
            "SCOPE":          {"value": ", ".join(config.SCOPE) if config.SCOPE else "—", "sensitive": False},
            "ADMIN_GROUP_ID": {"is_set": bool(config.ADMIN_GROUP_ID),"sensitive": True},
        },
        session={
            "SESSION_TIMEOUT": {"value": config.SESSION_TIMEOUT,      "sensitive": False},
            "SECRET_KEY":      {"is_set": bool(config.SECRET_KEY),    "sensitive": True},
        },
    ))


# ── Companies ─────────────────────────────────────────────────────────────────

class CompanyItem(BaseModel):
    name: str
    # Ziffern-Strings, damit führende Nullen erhalten bleiben (z.B. "00896").
    pnr_from: Optional[str] = None
    pnr_to: Optional[str] = None
    mandant: Optional[str] = None
    # Teilt sich den Zähler mit dieser Firma (dann kein eigener Bereich).
    pnr_shared_with: Optional[str] = None
    # alphacore-Firmen-ID (Directus-Fremdschlüssel), optional gepflegt.
    directus_firma_id: Optional[str] = None
    # E-Mail-Domain der Firma (Basis der automatischen Firmenmail), optional.
    domain: Optional[str] = None
    # Übernimmt die Dokument-Vorlagen dieser Firma (dann keine eigenen genutzt).
    documents_shared_with: Optional[str] = None
    # Nur beim GET befüllt (Anzeige) – wird beim PUT ignoriert / aus dem Bestand bewahrt.
    pnr_current: Optional[int] = None
    pnr_warned: bool = False


class CompaniesOut(BaseModel):
    companies: list[CompanyItem]


class CompaniesIn(BaseModel):
    companies: list[CompanyItem]


@router.get("/settings/companies", response_model=DataResponse[CompaniesOut])
def get_companies_endpoint(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=CompaniesOut(companies=[CompanyItem(**c) for c in get_companies_full()]))


@router.put("/settings/companies", response_model=DataResponse[CompaniesOut])
def set_companies_endpoint(payload: CompaniesIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    old_companies = get_companies_full()

    cleaned: list[dict] = []
    seen = set()
    for c in payload.companies:
        name = (c.name or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        mandant = (c.mandant or "").strip() or None
        shared = (c.pnr_shared_with or "").strip() or None
        firma_id = (c.directus_firma_id or "").strip() or None
        dom = (c.domain or "").strip().lower().lstrip("@") or None
        docs_from = (c.documents_shared_with or "").strip() or None
        if docs_from and docs_from.casefold() == name.casefold():
            raise HTTPException(422, f"„{name}“: kann die Dokument-Vorlagen nicht von sich selbst übernehmen.")

        if shared:
            # Teilt den Zähler → kein eigener Bereich.
            if shared.casefold() == name.casefold():
                raise HTTPException(422, f"„{name}“: kann den Zähler nicht mit sich selbst teilen.")
            cleaned.append({
                "name": name, "pnr_from": None, "pnr_to": None,
                "mandant": mandant, "pnr_shared_with": shared,
                "directus_firma_id": firma_id, "domain": dom,
                "documents_shared_with": docs_from,
            })
            continue

        # Eigener Bereich – Ziffern-Strings (führende Nullen erlaubt, z.B. "00896").
        pf = str(c.pnr_from).strip() if c.pnr_from not in (None, "") else None
        pt = str(c.pnr_to).strip() if c.pnr_to not in (None, "") else None
        if (pf is None) != (pt is None):
            raise HTTPException(422, f"„{name}“: Bitte Von und Bis der Personalnummern beide angeben (oder beide leer lassen).")
        if pf is not None:
            if not pf.isdigit() or not pt.isdigit():
                raise HTTPException(422, f"„{name}“: Personalnummern dürfen nur aus Ziffern bestehen.")
            if int(pf) > int(pt):
                raise HTTPException(422, f"„{name}“: „Von“ darf nicht größer als „Bis“ sein.")
        cleaned.append({
            "name": name, "pnr_from": pf, "pnr_to": pt,
            "mandant": mandant, "pnr_shared_with": None,
            "directus_firma_id": firma_id, "domain": dom,
            "documents_shared_with": docs_from,
        })

    if not cleaned:
        raise HTTPException(422, "Mindestens eine Firma erforderlich")

    # Geteilte Zähler: das Ziel muss eine Firma mit EIGENEM Nummernbereich sein.
    owners = {c["name"] for c in cleaned if not c["pnr_shared_with"] and c["pnr_from"] is not None}
    for c in cleaned:
        if c["pnr_shared_with"] and c["pnr_shared_with"] not in owners:
            raise HTTPException(
                422,
                f"„{c['name']}“: teilt den Zähler mit „{c['pnr_shared_with']}“, aber diese Firma "
                "hat keinen eigenen Personalnummern-Bereich.",
            )

    # Übernommene Dokument-Vorlagen: Ziel muss existieren und darf NICHT selbst
    # übernehmen (keine Ketten – die Auflösung macht nur EINEN Hop).
    by_name = {c["name"]: c for c in cleaned}
    for c in cleaned:
        src = c["documents_shared_with"]
        if not src:
            continue
        target = by_name.get(src)
        if target is None:
            raise HTTPException(
                422,
                f"„{c['name']}“: übernimmt die Dokument-Vorlagen von „{src}“, aber diese "
                "Firma gibt es nicht.",
            )
        if target["documents_shared_with"]:
            raise HTTPException(
                422,
                f"„{c['name']}“: „{src}“ übernimmt selbst Vorlagen von „{target['documents_shared_with']}“ "
                "– Vorlagen lassen sich nicht über mehrere Firmen weiterreichen. Bitte direkt "
                "die Firma mit den eigenen Vorlagen wählen.",
            )
        # Eine übernehmende Firma hat KEINE eigenen Vorlagen (sonst lägen unsichtbare
        # „schlafende“ Vorlagen in der DB, die Umbenennen/Löschen blockieren und bei
        # Namens-Kollision statt der übernommenen gefüllt würden). Erst entfernen.
        own = ctpl_db.list_for_company(c["name"])
        if own:
            namen = ", ".join(f"„{t['name']}“" for t in own)
            raise HTTPException(
                422,
                f"„{c['name']}“ hat noch eigene Dokument-Vorlagen ({namen}). Bitte diese "
                f"zuerst entfernen, dann lassen sich die Vorlagen von „{src}“ übernehmen.",
            )

    # Firmen-Vorlagen hängen am NAMEN (keine stabile ID): eine Firma mit hinterlegten
    # Dokument-Vorlagen darf nicht spurlos gelöscht/umbenannt werden, sonst zeigt der
    # Prozess ins Leere und Arbeitsvertrag/Kündigung ließen sich nicht mehr erzeugen.
    # Umbenennen = alter Name verschwindet → gleiche Sperre.
    new_names = {c["name"] for c in cleaned}
    for old in old_companies:
        old_name = (old.get("name") or "").strip()
        if not old_name or old_name in new_names:
            continue
        tpls = ctpl_db.list_for_company(old_name)
        if tpls:
            namen = ", ".join(f"„{t['name']}“" for t in tpls)
            raise HTTPException(
                409,
                f"„{old_name}“ hat noch hinterlegte Dokument-Vorlagen ({namen}). "
                "Bitte diese Vorlagen zuerst entfernen, bevor die Firma gelöscht "
                "oder umbenannt wird.",
            )

    try:
        set_companies_full(cleaned)
    except Exception as e:
        logger.exception("Failed to update companies: %s", e)
        raise HTTPException(500, "Fehler beim Speichern")

    created, deleted, modified = _diff_companies(old_companies, cleaned)
    parts = ([f"„{n}“ angelegt" for n in created]
             + [f"„{n}“ gelöscht" for n in deleted]
             + [f"„{m['name']}“: {'; '.join(m['changes'])}" for m in modified])
    if parts:
        _audit(user, "companies_changed", entity_type="settings", entity_id="companies",
               summary=_summary(parts, "Firmen"),
               details={"created": created, "deleted": deleted, "modified": modified})

    return DataResponse(data=CompaniesOut(companies=[CompanyItem(**c) for c in get_companies_full()]))


# ── Firmen-Dokument-Vorlagen (.docx/PDF je Firma, nach Name) ──────────────────
#
# Firmenabhängige Dokumente (Arbeitsvertrag, Kündigung …): je Firma beliebig viele
# benannte Vorlagen. Ein Prozess-Dokument verweist nur über den NAMEN; welche Datei
# gefüllt wird, entscheidet die im Auftrag gewählte Firma (siehe DocumentSpec
# .companyTemplate/.companyField + process_tickets._load_template_row).

def _ctpl_info(row: dict) -> dict:
    """Metadaten einer Firmen-Vorlage + erkanntes Format und gefundene {{marker}}.

    Verweis-Zeile (ref_company gesetzt, keine eigene Datei): Format/Platzhalter werden
    aus der VERWIESENEN Datei der Ziel-Firma gelesen, damit der Editor die echten
    Angaben zeigt; `ref_company` nennt die Quelle."""
    from pathlib import Path
    ref = row.get("ref_company")
    info = {"name": row["name"], "filename": row.get("original_filename"),
            "size": row.get("size_bytes"),
            "uploaded_at": (row["uploaded_at"].isoformat()
                            if hasattr(row.get("uploaded_at"), "isoformat") else row.get("uploaded_at")),
            "uploaded_by": row.get("uploaded_by_name"), "format": None, "placeholders": [],
            "ref_company": ref or None}
    # Für eine Verweis-Zeile die Ziel-Datei als Quelle für Format/Platzhalter nehmen.
    src_row = ctpl_db.get_template(ref, row["name"]) if ref else row
    if not (src_row and src_row.get("stored_path")):
        return info
    if ref:
        info["filename"] = src_row.get("original_filename")
        info["size"] = src_row.get("size_bytes")
    try:
        data = Path(storage.full_path(src_row["stored_path"])).read_bytes()
        info["format"] = template_format.detect(data)
        if template_format.is_pdf(data):
            from backend.services import pdf_fill
            info["placeholders"] = pdf_fill.find_placeholders(data)
        else:
            from backend.services import docx_fill
            info["placeholders"] = docx_fill.find_placeholders(data)
    except Exception:
        logger.warning("Firmen-Vorlage „%s/%s“ nicht lesbar", src_row.get("company"), src_row.get("name"))
    return info


def _require_known_company(company: str) -> str:
    c = (company or "").strip()
    if c not in get_companies():
        raise HTTPException(404, f"Unbekannte Firma: {company}")
    return c


def _content_disposition(filename: str) -> str:
    """Content-Disposition mit ASCII-Fallback + RFC-5987 filename* – Starlette
    kodiert Header als latin-1, ein Umlaut/Gedankenstrich im Dateinamen würde sonst
    einen 500 werfen."""
    import urllib.parse
    fn = (filename or "Dokument").replace('"', "")
    ascii_name = fn.encode("ascii", "replace").decode("ascii")
    quoted = urllib.parse.quote(fn)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


# ── Dokument-Vorlagen-Typen (Labels) ──────────────────────────────────────────
#
# Verwaltete Liste der Vorlagen-Typen (Arbeitsvertrag, Kündigung …). Firmen laden
# ihre Vorlagen je Typ hoch; der Prozess referenziert den Typ. Pro Typ EIN
# kanonischer {{Platzhalter}}-Satz (beim ersten Upload erfasst, danach erzwungen).

class TemplateLabelOut(BaseModel):
    name: str
    placeholders: Optional[list[str]] = None   # kanonischer Satz (None = noch offen)
    companies: list[str] = []                   # Firmen mit einer Vorlage dieses Typs


class TemplateLabelsOut(BaseModel):
    labels: list[TemplateLabelOut]


class TemplateLabelsIn(BaseModel):
    labels: list[str]


def _company_usage_cf() -> dict[str, list[str]]:
    """casefold(Typname) → Firmen mit einer EIGENEN Datei dieses Typs. Case-insensitiv,
    weil die DB-Spalte company_document_templates.name case-insensitiv vergleicht,
    die Typ-Namen aber abweichend geschrieben sein können (Altbestand). Verweis-Zeilen
    (ref_company, keine eigene Datei) zählen NICHT – so sind das zugleich genau die
    Firmen, auf die ein Pro-Dokument-Verweis dieses Typs zeigen darf."""
    out: dict[str, list[str]] = {}
    for r in ctpl_db.list_all():
        if r.get("stored_path"):
            out.setdefault(r["name"].casefold(), []).append(r["company"])
    return out


def _labels_with_usage() -> list[TemplateLabelOut]:
    by_cf = _company_usage_cf()
    return [TemplateLabelOut(name=l["name"], placeholders=l.get("placeholders"),
                             companies=sorted(by_cf.get(l["name"].casefold(), [])))
            for l in get_template_labels()]


def _types_used_by_processes() -> dict[str, list[str]]:
    """casefold(Typname) → veröffentlichte Prozesse, die ihn als companyTemplate
    referenzieren. Verhindert das Löschen/Umbenennen eines noch verdrahteten Typs."""
    from backend.database import process_definitions as pdef_db
    out: dict[str, list[str]] = {}
    try:
        rows = pdef_db.list_published_catalog(include_definition=True)
    except Exception:
        return out
    for row in rows:
        defn = row.get("definition") or {}
        for ph in defn.get("phases", []) or []:
            for d in (ph.get("documents") or []):
                ct = (d.get("companyTemplate") or "").strip()
                if ct:
                    keys = out.setdefault(ct.casefold(), [])
                    if row.get("key") and row["key"] not in keys:
                        keys.append(row["key"])
    return out


def _seed_labels_if_empty() -> None:
    """Einmalige Migration: früher per Freitext hochgeladene Vorlagen-Namen als Typen
    übernehmen, damit Bestands-Vorlagen nach der Umstellung weiter als Typ auswählbar
    sind. Idempotent – läuft nur, solange noch kein Typ registriert ist.

    Bewusst OHNE automatische Baseline: bei Altbestand können die Dateien mehrerer
    Firmen unter demselben Namen abweichende Platzhalter haben – ein aus EINER Datei
    gegriffener Satz wäre willkürlich. Die Baseline pegelt sich beim nächsten Upload
    je Typ ein (und erzwingt dann Gleichheit)."""
    if get_template_labels():
        return
    # Nach Name case-insensitiv deduplizieren (DB erlaubt case-Varianten je Firma);
    # die erste gesehene Schreibweise wird kanonisch.
    seen: set[str] = set()
    names: list[str] = []
    for r in ctpl_db.list_all():
        if r["name"].casefold() not in seen:
            seen.add(r["name"].casefold())
            names.append(r["name"])
    if names:
        set_template_labels(names)


@router.get("/settings/document-template-labels", response_model=DataResponse[TemplateLabelsOut])
def get_template_labels_endpoint(user: dict = Depends(get_current_user)):
    require_admin(user)
    _seed_labels_if_empty()
    return DataResponse(data=TemplateLabelsOut(labels=_labels_with_usage()))


@router.put("/settings/document-template-labels", response_model=DataResponse[TemplateLabelsOut])
def set_template_labels_endpoint(payload: TemplateLabelsIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    for n in payload.labels:
        if len(str(n).strip()) > 150:             # Vorlagen-Name-Spalte ist VARCHAR(150)
            raise HTTPException(422, f"Typ-Name zu lang (max. 150 Zeichen): „{str(n).strip()[:60]}…“")
    old = {l["name"] for l in get_template_labels()}
    new_cf = {str(n).strip().casefold() for n in payload.labels if str(n).strip()}
    # Einen Typ, der noch GENUTZT wird, nicht entfernen/umbenennen (sonst zeigen
    # Prozess-Dokumente ins Leere und die Firmen-Vorlagen würden verwaisen). Genutzt =
    # eine Firma hat eine Vorlage ODER ein veröffentlichter Prozess referenziert ihn.
    in_use = _company_usage_cf()
    proc_use = _types_used_by_processes()
    for name in old:
        cf = name.casefold()
        if cf in new_cf:
            continue
        if in_use.get(cf):
            firmen = ", ".join(f"„{c}“" for c in sorted(in_use[cf]))
            raise HTTPException(
                409,
                f"Vorlagen-Typ „{name}“ wird noch von {firmen} genutzt. Bitte zuerst dort "
                "die Vorlagen entfernen, bevor der Typ gelöscht oder umbenannt wird.")
        if proc_use.get(cf):
            prozesse = ", ".join(f"„{k}“" for k in sorted(proc_use[cf]))
            raise HTTPException(
                409,
                f"Vorlagen-Typ „{name}“ wird noch von Prozess(en) {prozesse} verwendet. "
                "Bitte dort erst den Typ im Dokument ändern/entfernen, dann lässt er sich löschen.")
    labels = set_template_labels(payload.labels)
    created = sorted(l["name"] for l in labels if l["name"] not in old)
    deleted = sorted(n for n in old if n.casefold() not in new_cf)
    if created or deleted:
        parts = [f"„{n}“ angelegt" for n in created] + [f"„{n}“ entfernt" for n in deleted]
        _audit(user, "template_labels_changed", entity_type="settings",
               entity_id="document_template_labels",
               summary=_summary(parts, "Vorlagen-Typen"),
               details={"created": created, "deleted": deleted})
    return DataResponse(data=TemplateLabelsOut(labels=_labels_with_usage()))


@router.get("/settings/companies/{company}/documents")
def list_company_documents(company: str, own: bool = Query(False),
                           user: dict = Depends(get_current_user)):
    """Benannte Dokument-Vorlagen einer Firma (Verwaltung im Companies-Panel).
    Übernimmt die Firma Vorlagen von einer anderen, werden DEREN Vorlagen geliefert
    (read-only); `shared_from` nennt die Quelle. `own=1` umgeht die Auflösung und
    liefert den EIGENEN Bestand – der Editor prüft damit vor dem Übernehmen auf noch
    vorhandene eigene Vorlagen."""
    require_admin(user)
    c = _require_known_company(company)
    src = c if own else template_source_company(c)
    shared_from = None if own else (src if src != c else None)
    return DataResponse(data={"documents": [_ctpl_info(r) for r in ctpl_db.list_for_company(src)],
                              "shared_from": shared_from})


@router.post("/settings/companies/{company}/documents")
async def upload_company_document(company: str, name: str = Query(...),
                                  file: UploadFile = File(...),
                                  user: dict = Depends(get_current_user)):
    """Vorlage (.docx/PDF) eines Vorlagen-TYPS für eine Firma hochladen/ersetzen.

    Der Name muss ein registrierter Typ sein (Dropdown, kein Freitext). Alle Firmen-
    Vorlagen desselben Typs müssen denselben {{Platzhalter}}-Satz haben – der erste
    Upload legt ihn fest, weitere werden dagegen geprüft (422 mit Diff)."""
    require_admin(user)
    c = _require_known_company(company)
    src = template_source_company(c)
    if src != c:
        raise HTTPException(
            409,
            f"„{c}“ übernimmt die Dokument-Vorlagen von „{src}“. Bitte dort hochladen "
            "oder diese Firma zuerst auf eigene Vorlagen umstellen.",
        )
    # Name muss ein registrierter Vorlagen-Typ sein; kanonische Schreibweise nutzen.
    _seed_labels_if_empty()                       # Bestands-Namen einmalig als Typen übernehmen
    label = get_template_label(name)
    if label is None:
        raise HTTPException(
            422, f"„{(name or '').strip()}“ ist kein bekannter Vorlagen-Typ. Bitte den Typ "
                 "zuerst unter Einstellungen → Vorlagen-Typen anlegen.")
    tpl_name = label["name"]
    fname = (file.filename or "").lower()
    if not (fname.endswith(".docx") or fname.endswith(".pdf")):
        raise HTTPException(422, "Nur Word- (.docx) oder PDF-Dateien werden als Vorlage unterstützt")
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        stored_path, size, _sha = storage.save_stream(file.file, max_bytes=max_bytes)
    except storage.FileTooLarge:
        raise HTTPException(413, f"Datei zu groß (max. {config.MAX_UPLOAD_MB} MB)")
    # Lesbarkeit UND Parsebarkeit prüfen (echte .docx/PDF mit lesbaren Markern) –
    # detect() allein wirft nie; ohne find_placeholders fiele eine kaputte Datei erst
    # beim Erzeugen im Onboarding als 500 auf. Bei Fehler Blob gleich wieder entfernen.
    from pathlib import Path
    try:
        data = Path(storage.full_path(stored_path)).read_bytes()
        fmt = template_format.detect(data)
        if template_format.is_pdf(data):
            from backend.services import pdf_fill
            markers = pdf_fill.find_placeholders(data)
        else:
            from backend.services import docx_fill
            markers = docx_fill.find_placeholders(data)
    except Exception:
        storage.delete(stored_path)
        raise HTTPException(422, "Die Datei ließ sich nicht als Word- (.docx) oder PDF-Vorlage lesen")
    # Harte Platzhalter-Prüfung gegen den kanonischen Satz des Typs. Baseline None →
    # dieser Upload legt sie fest (unten nach erfolgreichem Speichern).
    baseline = label.get("placeholders")
    if baseline is not None and set(markers) != set(baseline):
        storage.delete(stored_path)
        fehlt = sorted(set(baseline) - set(markers))
        extra = sorted(set(markers) - set(baseline))
        teile = []
        if fehlt:
            teile.append("fehlt: " + ", ".join("{{%s}}" % m for m in fehlt))
        if extra:
            teile.append("zusätzlich: " + ", ".join("{{%s}}" % m for m in extra))
        raise HTTPException(
            422,
            f"Die Platzhalter weichen vom Typ „{tpl_name}“ ab ({'; '.join(teile)}). "
            "Alle Firmen-Vorlagen eines Typs müssen dieselben {{Platzhalter}} haben. "
            "Datei anpassen – oder den Marker-Satz des Typs ändern (dazu zuerst alle "
            "vorhandenen Vorlagen dieses Typs entfernen).")
    old = ctpl_db.get_template(c, tpl_name)
    try:
        ctpl_db.set_template(company=c, name=tpl_name, stored_path=stored_path,
                             original_filename=file.filename or tpl_name,
                             content_type=file.content_type, size_bytes=size,
                             uploaded_by_id=user.get("id"),
                             uploaded_by_name=user.get("displayName") or user.get("email"))
    except Exception:
        storage.delete(stored_path)               # DB-Fehler → neuen Blob nicht verwaisen lassen
        raise
    if old and old.get("stored_path") and old["stored_path"] != stored_path:
        storage.delete(old["stored_path"])
    if baseline is None:                          # erster Upload → kanonischen Satz festlegen
        set_template_label_baseline(tpl_name, list(markers))
    _audit(user, "company_template_uploaded",
           summary=f"Firmen-Vorlage „{tpl_name}“ für „{c}“ hochgeladen ({fmt}, {size} B)",
           details={"company": c, "name": tpl_name, "format": fmt})
    return DataResponse(data=_ctpl_info(ctpl_db.get_template(c, tpl_name)))


class DocumentReferenceIn(BaseModel):
    ref_company: str


@router.put("/settings/companies/{company}/documents/{name}/reference")
def reference_company_document(company: str, name: str, payload: DocumentReferenceIn,
                               user: dict = Depends(get_current_user)):
    """Für EINEN Vorlagen-Typ dieser Firma auf die gleichnamige Datei einer ANDEREN
    Firma verweisen – statt einer eigenen Datei (Pro-Dokument-Verweis, analog zum
    Teilen der Personalnummern). Genau EIN Sprung: das Ziel muss eine eigene Datei
    dieses Typs haben (kein Verweis-auf-Verweis)."""
    require_admin(user)
    c = _require_known_company(company)
    src = template_source_company(c)
    if src != c:
        raise HTTPException(
            409, f"„{c}“ übernimmt bereits alle Vorlagen von „{src}“. Bitte diese Firma "
                 "zuerst auf eigene Vorlagen umstellen, dann lässt sich je Typ verweisen.")
    _seed_labels_if_empty()
    label = get_template_label(name)
    if label is None:
        raise HTTPException(
            422, f"„{(name or '').strip()}“ ist kein bekannter Vorlagen-Typ. Bitte den Typ "
                 "zuerst unter Einstellungen → Vorlagen-Typen anlegen.")
    tpl_name = label["name"]
    ref = (payload.ref_company or "").strip()
    if not ref or ref not in get_companies():
        raise HTTPException(422, f"Unbekannte Ziel-Firma: „{ref}“")
    if ref.casefold() == c.casefold():
        raise HTTPException(422, "Eine Firma kann nicht auf sich selbst verweisen.")
    target = ctpl_db.get_template(ref, tpl_name)
    if target and target.get("ref_company"):
        raise HTTPException(
            422, f"„{ref}“ verweist für „{tpl_name}“ selbst weiter – Verweise lassen sich "
                 "nicht verketten. Bitte direkt die Firma mit der eigenen Datei wählen.")
    if not (target and target.get("stored_path")):
        raise HTTPException(
            422, f"„{ref}“ hat keine eigene Vorlage „{tpl_name}“, auf die verwiesen werden "
                 "könnte. Dort zuerst hochladen.")
    old = ctpl_db.get_template(c, tpl_name)
    ctpl_db.set_reference(c, tpl_name, ref)
    if old and old.get("stored_path"):
        storage.delete(old["stored_path"])        # bisherige eigene Datei → durch Verweis ersetzt
    _audit(user, "company_template_referenced",
           summary=f"Firmen-Vorlage „{tpl_name}“ für „{c}“ verweist nun auf „{ref}“",
           details={"company": c, "name": tpl_name, "ref_company": ref})
    return DataResponse(data=_ctpl_info(ctpl_db.get_template(c, tpl_name)))


@router.get("/settings/companies/{company}/documents/{name}/download")
def download_company_document(company: str, name: str, user: dict = Depends(get_current_user)):
    require_admin(user)
    # Firmenweite Übernahme (documents_shared_with) UND Pro-Dokument-Verweis
    # (ref_company) auflösen – wie die Liste/Füll-Logik; sonst zeigt die Liste die
    # Quell-/Verweis-Datei, der Download aber ginge ins Leere → 404.
    row = ctpl_db.resolve_company_template((company or "").strip(), (name or "").strip())
    if not row or not row.get("stored_path"):
        raise HTTPException(404, "Keine Vorlage hinterlegt")
    from pathlib import Path
    try:
        data = Path(storage.full_path(row["stored_path"])).read_bytes()
    except Exception:
        raise HTTPException(500, "Die hinterlegte Vorlage ist nicht lesbar")
    mime = ("application/pdf" if template_format.is_pdf(data)
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": _content_disposition(
                        row.get("original_filename") or name)})


@router.delete("/settings/companies/{company}/documents/{name}")
def delete_company_document(company: str, name: str, user: dict = Depends(get_current_user)):
    require_admin(user)
    tpl_name = (name or "").strip()
    row = ctpl_db.delete_template((company or "").strip(), tpl_name)
    if row and row.get("stored_path"):
        storage.delete(row["stored_path"])
    # War das die LETZTE Vorlage dieses Typs? Dann den kanonischen Platzhalter-Satz
    # freigeben, damit sich der Typ neu einpegeln (Marker ändern) lässt. Case-insensitiv
    # vergleichen – die DB-Spalte tut es auch, Typ-Namen können abweichend geschrieben
    # sein (Altbestand); sonst würde die Baseline trotz noch vorhandener Vorlage geleert.
    cf = tpl_name.casefold()
    if not any(r["name"].casefold() == cf and r.get("stored_path") for r in ctpl_db.list_all()):
        set_template_label_baseline(tpl_name, None)
    _audit(user, "company_template_deleted",
           summary=f"Firmen-Vorlage „{name}“ für „{company}“ entfernt",
           details={"company": (company or "").strip(), "name": tpl_name})
    return DataResponse(data={"exists": False})


# ── Prozess-Anzeigereihenfolge (Katalog „Neues Prozess-Ticket") ───────────────
#
# Der Admin ordnet ALLE veröffentlichten Prozesse; die Reihenfolge gilt global im
# Katalog. WELCHE Prozesse jemand dort sieht, entscheidet weiterhin `may_create`
# – die Reihenfolge ändert daran nichts. Das Basis-Ticket ist ausgenommen (eigener
# Einstieg, taucht im Prozess-Katalog nicht auf).

class ProcessOrderItem(BaseModel):
    key: str
    name: str
    icon: Optional[str] = None


class ProcessOrderOut(BaseModel):
    items: list[ProcessOrderItem]


class ProcessOrderIn(BaseModel):
    order: list[str]


def _process_order_items() -> list[ProcessOrderItem]:
    """Alle veröffentlichten Prozesse (ohne Basis-Ticket) in gespeicherter
    Reihenfolge; nicht Gelistetes stabil dahinter (nach Name)."""
    from backend.database import process_definitions as _pdefs
    from backend.services.seed_definitions import SYSTEM_PROCESS_KEYS

    items: list[ProcessOrderItem] = []
    for r in _pdefs.list_published_catalog(include_definition=True):
        key = r.get("key")
        if not key or key in SYSTEM_PROCESS_KEYS:   # Basis-Ticket: eigener Einstieg
            continue
        raw = r.get("definition") or {}
        items.append(ProcessOrderItem(key=key, name=r.get("name") or key, icon=raw.get("icon")))

    order = get_process_order()
    rank = {k: i for i, k in enumerate(order)}
    items.sort(key=lambda it: (rank.get(it.key, len(order)), it.name.lower()))
    return items


@router.get("/settings/process-order", response_model=DataResponse[ProcessOrderOut])
def get_process_order_endpoint(user: dict = Depends(get_current_user)):
    require_admin(user)
    return DataResponse(data=ProcessOrderOut(items=_process_order_items()))


@router.put("/settings/process-order", response_model=DataResponse[ProcessOrderOut])
def set_process_order_endpoint(payload: ProcessOrderIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    saved = set_process_order(payload.order)
    _audit(user, "process_order_changed", entity_type="settings", entity_id="process-order",
           summary=f"Prozess-Reihenfolge geändert ({len(saved)} Einträge)",
           details={"order": saved})
    return DataResponse(data=ProcessOrderOut(items=_process_order_items()))


# ── AD Groups (Cache) ────────────────────────────────────────────────────────

class AdGroupOut(BaseModel):
    id: str
    displayName: str
    description: str


@router.get("/settings/ad-groups", response_model=DataResponse[list[AdGroupOut]])
def list_ad_groups(request: Request, user: dict = Depends(get_current_user)):
    """Gibt alle AD-Gruppen aus dem Cache zurück (für Dropdowns)."""
    require_admin(user)
    groups = getattr(request.app.state, "group_cache", [])
    return DataResponse(data=[
        AdGroupOut(
            id=g["id"],
            displayName=g["displayName"],
            description=g.get("description", ""),
        )
        for g in groups
    ])


# ── Groups ────────────────────────────────────────────────────────────────────

class GroupOut(BaseModel):
    id: str
    name: str
    members: list[str]
    distributions: list[str]
    # True, wenn die Gruppe für die Prozesse gebraucht wird: entweder trägt sie
    # einen Pflicht-Namen (Namensquelle: seed_definitions) oder eine
    # Prozess-Definition referenziert ihre ID. Dann nicht lösch-/umbenennbar.
    required: bool = False
    # True → Gruppe wird in Auswahl-Dropdowns im Frontend nicht angezeigt
    # (z.B. Gruppen, die nur über spezielle Phasen automatisch zugewiesen werden).
    hidden: bool = False

class GroupCreate(BaseModel):
    name: str
    distributions: list[str] = []

class GroupUpdate(BaseModel):
    name: str
    members: list[str]
    distributions: list[str]
    hidden: bool = False

class MemberIn(BaseModel):
    user_id: str


class GroupBulkItem(BaseModel):
    id: Optional[str] = None          # None = neue Gruppe
    name: str
    members: list[str] = []
    distributions: list[str] = []
    hidden: bool = False


class GroupsBulkIn(BaseModel):
    groups: list[GroupBulkItem]


def _validate_emails(emails: list[str]) -> list[str]:
    cleaned = []
    for m in emails:
        m = m.strip().lower()
        if not EMAIL_REGEX.match(m):
            raise HTTPException(400, f"Ungültige E-Mail: '{m}'")
        cleaned.append(m)
    return list(set(cleaned))


def _group_out(g: dict, referenced_ids: Optional[set] = None) -> GroupOut:
    """GroupOut inkl. required-/hidden-Flag aus einem gespeicherten Gruppen-Dict bauen.

    `referenced_ids` ist die vorab EINMAL geladene Menge der in Definitionen
    referenzierten IDs. Ohne sie wird sie für diese eine Gruppe nachgeschlagen –
    in Listen deshalb immer mitgeben, sonst läuft eine Abfrage pro Zeile (N+1).
    """
    if referenced_ids is None:
        referenced_ids = _referenced_group_ids({g["id"]})
    return GroupOut(
        id=g["id"],
        name=g["name"],
        members=g.get("members", []),
        distributions=g.get("distributions", []),
        required=_is_required_group_name(g["name"]) or g["id"] in referenced_ids,
        hidden=bool(g.get("hidden", False)),
    )


def _groups_out(groups: list[dict]) -> list[GroupOut]:
    """Ganze Liste – Referenz-Prüfung für alle IDs in EINER Abfrage."""
    referenced = _referenced_group_ids({g["id"] for g in groups})
    return [_group_out(g, referenced) for g in groups]


@router.get("/settings/groups", response_model=DataResponse[list[GroupOut]])
def list_groups(user: dict = Depends(get_current_user)):
    require_admin(user)
    groups = get_groups()
    for g in groups:
        g.setdefault("distributions", [])
    return DataResponse(data=_groups_out(groups))


@router.put("/settings/groups", response_model=DataResponse[list[GroupOut]])
def set_groups_bulk(payload: GroupsBulkIn, request: Request, user: dict = Depends(get_current_user)):
    """Bulk-Replace der Fachabteilungen (wie PUT /settings/companies): das Frontend
    schickt die komplette gewünschte Liste; anlegen/ändern/löschen passiert in einem
    Schritt. Pflichtgruppen dürfen nicht gelöscht/umbenannt werden."""
    require_admin(user)
    valid_ids = {u["id"] for u in getattr(request.app.state, "user_cache", [])}
    old_groups = get_groups()

    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in payload.groups:
        name = item.name.strip()
        if not name:
            raise HTTPException(400, "Jede Fachabteilung braucht einen Namen")
        if name.lower() in seen:
            raise HTTPException(400, f"Doppelter Name: '{name}'")
        seen.add(name.lower())
        for m in item.members:
            if m not in valid_ids:
                raise HTTPException(400, f"Ungültige User-ID '{m}'")
        cleaned.append({
            "id": item.id or uuid.uuid4().hex,
            "name": name,
            "members": list(dict.fromkeys(item.members)),
            "distributions": _validate_emails(item.distributions),
            "hidden": bool(item.hidden),
        })

    # Pflichtgruppen (von den Prozessen benötigt) müssen erhalten bleiben. Der
    # Check über die NAMEN erfasst Löschen UND Umbenennen in einem Zug: fehlt der
    # Name in der neuen Liste, ist die Gruppe entweder weg oder heißt anders.
    from backend.services.seed_definitions import required_group_names
    present = {c["name"].strip().lower() for c in cleaned}
    for req in required_group_names():
        if (req or "").strip().lower() not in present:
            raise HTTPException(
                409, f"Die Pflicht-Fachabteilung '{req}' darf nicht gelöscht oder umbenannt werden.",
            )

    removed_ids = {g["id"] for g in old_groups} - {c["id"] for c in cleaned}
    _assert_groups_unreferenced(removed_ids)

    save_groups(cleaned)

    names = _names_from(request)
    created, deleted, modified = _diff_groups(old_groups, cleaned, lambda i: names.get(i, i))
    parts = ([f"„{n}“ angelegt" for n in created]
             + [f"„{n}“ gelöscht" for n in deleted]
             + [f"„{m['name']}“: {'; '.join(m['changes'])}" for m in modified])
    if parts:
        _audit(user, "groups_changed", entity_type="settings", entity_id="groups",
               summary=_summary(parts, "Fachabteilungen"),
               details={"created": created, "deleted": deleted, "modified": modified})

    groups = get_groups()
    for g in groups:
        g.setdefault("distributions", [])
    return DataResponse(data=_groups_out(groups))


@router.post("/settings/groups", response_model=DataResponse[GroupOut], status_code=201)
def create_group(payload: GroupCreate, user: dict = Depends(get_current_user)):
    require_admin(user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Name erforderlich")
    groups = get_groups()
    if any(g["name"].lower() == name.lower() for g in groups):
        raise HTTPException(400, f"Gruppe '{name}' existiert bereits")
    new = {
        "id": uuid.uuid4().hex,
        "name": name,
        "members": [],
        "distributions": _validate_emails(payload.distributions),
    }
    groups.append(new)
    save_groups(groups)
    _audit(user, "group_created", entity_type="group", entity_id=new["id"], summary=name)
    return DataResponse(data=_group_out(new))


@router.put("/settings/groups/{group_id}", response_model=DataResponse[GroupOut])
def update_group(
    group_id: str,
    payload: GroupUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    valid_ids = {u["id"] for u in request.app.state.user_cache}
    for m in payload.members:
        if m not in valid_ids:
            raise HTTPException(400, f"Ungültige User-ID '{m}'")
    new_name = payload.name.strip()
    groups = get_groups()
    for g in groups:
        if g["id"] == group_id:
            # Pflichtgruppen dürfen nicht umbenannt werden – die ausgelieferten
            # Prozesse werden über den NAMEN auf die Gruppe aufgelöst (siehe
            # seed_definitions). Mitglieder/Verteiler bleiben editierbar.
            if _is_required_group_name(g["name"]) and new_name.lower() != g["name"].lower():
                raise HTTPException(
                    409,
                    f"Die Fachabteilung '{g['name']}' wird von den Prozessen benötigt "
                    f"und kann nicht umbenannt werden.",
                )
            g["name"]          = new_name
            g["members"]       = payload.members
            g["distributions"] = _validate_emails(payload.distributions)
            g["hidden"]        = bool(payload.hidden)
            save_groups(groups)
            _audit(user, "group_updated", entity_type="group", entity_id=group_id, summary=new_name)
            return DataResponse(data=_group_out(g))
    raise HTTPException(404, "Gruppe nicht gefunden")


@router.delete("/settings/groups/{group_id}", status_code=204)
def delete_group(group_id: str, user: dict = Depends(get_current_user)):
    require_admin(user)
    groups = get_groups()
    target = next((g for g in groups if g["id"] == group_id), None)
    if not target:
        raise HTTPException(404, "Gruppe nicht gefunden")
    # Pflicht-Fachabteilungen dürfen nicht gelöscht werden.
    if _is_required_group_name(target["name"]):
        raise HTTPException(
            409,
            f"Die Fachabteilung '{target['name']}' wird von den Prozessen benötigt "
            f"und kann nicht gelöscht werden.",
        )
    # …ebenso wenig von Prozess-Definitionen referenzierte (gleicher Schutz wie im Bulk-Pfad).
    _assert_groups_unreferenced({group_id})
    save_groups([g for g in groups if g["id"] != group_id])
    _audit(user, "group_deleted", entity_type="group", entity_id=group_id, summary=target["name"])


@router.post("/settings/groups/{group_id}/members", response_model=DataResponse[GroupOut])
def add_member(
    group_id: str,
    payload: MemberIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    valid_ids = {u["id"] for u in request.app.state.user_cache}
    if payload.user_id not in valid_ids:
        raise HTTPException(400, f"Ungültige User-ID '{payload.user_id}'")
    groups = get_groups()
    for g in groups:
        if g["id"] == group_id:
            if payload.user_id not in g["members"]:
                g["members"].append(payload.user_id)
            save_groups(groups)
            _audit(user, "group_member_added", entity_type="group", entity_id=group_id,
                   summary=g["name"], details={"user_id": payload.user_id})
            return DataResponse(data=_group_out(g))
    raise HTTPException(404, "Gruppe nicht gefunden")


@router.delete("/settings/groups/{group_id}/members/{user_id}", response_model=DataResponse[GroupOut])
def remove_member(
    group_id: str,
    user_id: str,
    user: dict = Depends(get_current_user),
):
    require_admin(user)
    groups = get_groups()
    for g in groups:
        if g["id"] == group_id:
            if user_id not in g["members"]:
                raise HTTPException(400, "User nicht in Gruppe")
            g["members"] = [m for m in g["members"] if m != user_id]
            save_groups(groups)
            _audit(user, "group_member_removed", entity_type="group", entity_id=group_id,
                   summary=g["name"], details={"user_id": user_id})
            return DataResponse(data=_group_out(g))
    raise HTTPException(404, "Gruppe nicht gefunden")


# ── Gruppen (öffentlich, für Dropdowns) ──────────────────────────────────────

class GroupSimpleOut(BaseModel):
    id: str
    name: str


@router.get("/groups", response_model=DataResponse[list[GroupSimpleOut]])
def list_groups_public(user: dict = Depends(get_current_user)):
    """
    Gibt die in Dropdowns auswählbaren Fachabteilungen zurück (id + name).
    Als 'hidden' markierte Gruppen werden hier ausgeblendet. Kein Admin nötig.
    """
    groups = get_groups()
    return DataResponse(data=[
        GroupSimpleOut(id=g["id"], name=g["name"])
        for g in groups
        if not g.get("hidden", False)
    ])


# ── Audit-Log ─────────────────────────────────────────────────────────────────

class AuditEntryOut(BaseModel):
    id: int
    created_at: str
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str = "user"
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    summary: Optional[str] = None
    details: dict = {}
    ip: Optional[str] = None


class AuditListOut(BaseModel):
    entries: list[AuditEntryOut]
    total: int
    actions: list[str]   # vorkommende Aktionen (für den Filter)


@router.get("/settings/audit-log", response_model=DataResponse[AuditListOut])
def get_audit_log(
    user: dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    actor: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    q: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
):
    require_admin(user)
    entries, total = list_audit(
        limit=limit, offset=offset, action=action, actor=actor,
        entity_type=entity_type, entity_id=entity_id, q=q, since=since, until=until,
    )
    return DataResponse(data=AuditListOut(
        entries=[AuditEntryOut(**e) for e in entries],
        total=total,
        actions=distinct_actions(),
    ))


# ── Test Mail ─────────────────────────────────────────────────────────────────

class TestMailIn(BaseModel):
    to: str

class TestMailOut(BaseModel):
    ok: bool
    message: str


@router.post("/settings/test-mail", response_model=DataResponse[TestMailOut])
def send_testmail(payload: TestMailIn, user: dict = Depends(get_current_user)):
    require_admin(user)
    to = payload.to.strip()
    if not EMAIL_REGEX.match(to):
        raise HTTPException(400, "Ungültige E-Mail-Adresse")
    try:
        send_test_mail(to)
        return DataResponse(data=TestMailOut(ok=True, message=f"Testmail an {to} gesendet"))
    except Exception as e:
        logger.exception("Test mail failed: %s", e)
        raise HTTPException(500, f"Fehler beim Senden: {e}")
