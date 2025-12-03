from fastapi import (
    APIRouter,
    Request,
    Depends,
    Query,
    HTTPException
)
from fastapi.responses import HTMLResponse

from alpharequestmanager.core.dependencies import get_current_user

import json as _json
from datetime import datetime, timedelta
from collections import Counter
from typing import Optional


router = APIRouter()


# =====================================================================
# Helpers aus server.py (vorerst lokal, später → analytics_service.py)
# =====================================================================

def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _date_key(dt: datetime) -> str:
    return dt.date().isoformat()


def _parse_range(date_from: Optional[str], date_to: Optional[str]):
    df = _parse_iso_dt(date_from)
    dt = _parse_iso_dt(date_to)

    if df and "T" not in (date_from or ""):
        df = df.replace(hour=0, minute=0, second=0, microsecond=0)

    if dt and "T" not in (date_to or ""):
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    return df, dt


def _parse_json_maybe(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return _json.loads(obj)
        except Exception:
            return None
    return None


def _owner_from_ticket(t) -> dict:
    raw = getattr(t, "owner_info", None)
    o = _parse_json_maybe(raw) or {}

    display = o.get("displayName") or o.get("display") or ""
    email = (o.get("email") or "").strip()
    domain = ""

    if "@" in email:
        domain = email.split("@", 1)[1].lower()

    company = o.get("company") or ""

    return {
        "display": display,
        "email": email,
        "domain": domain,
        "company": company,
    }


# =====================================================================
# ROUTE: Analytics-Seite
# =====================================================================

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        return request.app.state.manager  # just for type hinting
        return RedirectResponse("/dashboard", status_code=302)

    return request.app.templates.TemplateResponse(
        "analytics.html",
        {"request": request, "user": user, "is_admin": True}
    )


# =====================================================================
# ROUTE: Analytics Overview API
# =====================================================================

@router.get("/api/analytics/overview")
async def api_analytics_overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    owner_display: Optional[str] = Query(None),
    owner_domain: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    request: Request = None
):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    manager = request.app.state.manager

    df, dt = _parse_range(date_from, date_to)
    by_type = Counter()
    by_date = Counter()
    by_status = Counter()
    by_owner = Counter()

    facet_displays = set()
    facet_domains = set()

    owner_display = (owner_display or "").strip()
    owner_domain = (owner_domain or "").strip().lower()

    total = 0

    for t in manager.list_all():
        created = t.created_at

        # Date filter
        if df and created < df:
            continue
        if dt and created > dt:
            continue

        owner = _owner_from_ticket(t)

        # Collect facets
        if owner.get("display"):
            facet_displays.add(owner["display"])
        if owner.get("domain"):
            facet_domains.add(owner["domain"])

        # Apply filters
        if owner_display and owner.get("display") != owner_display:
            continue
        if owner_domain and owner.get("domain") != owner_domain:
            continue

        total += 1

        # Ticket Type
        try:
            o = _json.loads(t.description)
            ttype = o.get("ticketType") if isinstance(o, dict) else None
            if not (isinstance(ttype, str) and ttype.strip()):
                ttype = t.title or "Unbekannt"
        except Exception:
            ttype = t.title or "Unbekannt"

        by_type[str(ttype)] += 1

        # Date
        date_key = created.date().isoformat()
        by_date[date_key] += 1

        # Status
        st = getattr(t.status, "value", None) or str(t.status)
        by_status[str(st)] += 1

        # Owner
        disp = owner.get("display") or "Unbekannt"
        by_owner[disp] += 1

    # Build date range
    def _date_range(start: datetime, end: datetime):
        if not start or not end:
            return sorted(by_date.keys())
        delta = (end.date() - start.date()).days
        return [(start.date() + timedelta(days=i)).isoformat() for i in range(delta + 1)]

    date_range = _date_range(df, dt)
    by_date_rows = [{"date": d, "count": by_date.get(d, 0)} for d in date_range]

    # Status sort order
    order = ["pending", "approved", "rejected"]
    by_status_rows = sorted(
        by_status.items(),
        key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99)
    )

    return {
        "total_tickets": total,
        "by_type": [{"type": k, "count": v} for k, v in by_type.most_common()],
        "by_date": by_date_rows,
        "by_status": [{"status": k, "count": v} for k, v in by_status_rows],
        "by_owner": [{"owner": k, "count": v} for k, v in by_owner.most_common()],
        "facets": {
            "owner_displays": sorted(facet_displays),
            "owner_domains": sorted(facet_domains),
        },
    }


# =====================================================================
# ROUTE: Analytics Hardware Top
# =====================================================================

@router.get("/api/analytics/hardware/top")
async def api_analytics_hardware_top(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    owner_display: Optional[str] = Query(None),
    owner_domain: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    user: dict = Depends(get_current_user),
    request: Request = None
):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    manager = request.app.state.manager

    df, dt = _parse_range(date_from, date_to)
    counts = Counter()

    owner_display = (owner_display or "").strip()
    owner_domain = (owner_domain or "").strip().lower()

    for t in manager.list_all():
        created = t.created_at

        if df and created < df:
            continue
        if dt and created > dt:
            continue

        owner = _owner_from_ticket(t)

        if owner_display and owner.get("display") != owner_display:
            continue
        if owner_domain and owner.get("domain") != owner_domain:
            continue

        try:
            o = _json.loads(t.description)
        except Exception:
            continue

        if not isinstance(o, dict) or o.get("ticketType") != "Hardwarebestellung":
            continue

        data = o.get("data", {}) if isinstance(o, dict) else {}

        if isinstance(data, dict):
            # Artikel (Boolean Map)
            artikel = data.get("Artikel", {})
            if isinstance(artikel, dict):
                for name, flag in artikel.items():
                    if flag is True:
                        counts[str(name)] += 1

            # Monitor
            mon = data.get("Monitor")
            if isinstance(mon, dict) and mon.get("benoetigt") is True:
                try:
                    qty = int(mon.get("Anzahl") or 1)
                except Exception:
                    qty = 1
                counts["Monitor"] += max(qty, 1)

    return [
        {"item": k, "quantity": v}
        for k, v in counts.most_common(limit)
    ]
