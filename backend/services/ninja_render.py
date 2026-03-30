from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, Iterable

# =========================================
# Öffentliche API dieser Datei
# =========================================
__all__ = ["render_ticket_description", "ALPHAREQUEST_HEADLINE", "ALPHAREQUEST_WARNING_HTML"]

# =========================================
# Konfiguration / Konstante Texte
# =========================================
ALPHAREQUEST_HEADLINE = "AlphaRequest Ticket"
ALPHAREQUEST_WARNING_HTML = (
    '<div style="border-left:4px solid #f39c12;padding:8px 12px;margin:8px 0;">'
    "<strong>Wichtig:</strong> Änderungen in dieser Beschreibung werden <strong>nicht</strong> "
    "mit AlphaRequest synchronisiert. Bitte verwenden Sie die <strong>Ticketfelder</strong> rechts."
    "</div>"
)

# Defensivbegrenzung (abhängig von etwaigen Plattformlimits)
MAX_HTML_BODY_LEN = 8000

# =========================================
# Utilities (keine externen Abhängigkeiten)
# =========================================
_URL_RE = re.compile(r"(?P<url>https?://[^\s<]+)")
_EMAIL_RE = re.compile(r"(?P<mail>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _fmt_bool(v: Any) -> str:
    return "Ja" if bool(v) else "Nein"


def _fmt_dt(value: Any) -> str:
    """
    Akzeptiert Unix-TS (int/str) oder ISO-String und formatiert auf DE-Schema "DD.MM.YYYY HH:MM".
    Fällt bei unbekanntem Format auf str(value) zurück.
    """
    if value in (None, "", 0, "0"):
        return ""
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            ts = int(value)
            dt = datetime.fromtimestamp(ts)  # nimmt Server-TZ (oft UTC oder lokale TZ)
        else:
            # grob ISO-Parsing
            dt = datetime.fromisoformat(str(value))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def _linkify(text: str) -> str:
    if not text:
        return ""
    text = _esc(text)
    text = _URL_RE.sub(r'<a href="\g<url>">\g<url></a>', text)
    text = _EMAIL_RE.sub(r'<a href="mailto:\g<mail>">\g<mail></a>', text)
    return text


def _kv_row(label: str, value_html: str) -> str:
    if value_html in (None, "", []):
        return ""
    return (
        "<tr>"
        "<td style='padding:4px 8px;font-weight:600;vertical-align:top;'>"
        f"{_esc(label)}</td>"
        f"<td style='padding:4px 8px;'>{value_html}</td>"
        "</tr>"
    )


def _two_col_table(pairs: Iterable[tuple[str, str]]) -> str:
    rows = "".join(
        _kv_row(lbl, val) for (lbl, val) in pairs
        if val not in (None, "", [])
    )
    if not rows:
        return ""
    return f"<table style='border-collapse:collapse;width:100%;margin:8px 0;'>{rows}</table>"


def _section(title: str, inner_html: str) -> str:
    if not inner_html or not inner_html.strip():
        return ""
    return f"<h3 style='margin:12px 0 6px 0;'>{_esc(title)}</h3>{inner_html}"


def _wrap_base(inner_html: str, meta: Optional[Dict[str, str]] = None) -> str:
    """
    Fügt Headline + Warnhinweis + optionale Metazeile hinzu.
    """
    meta_line = ""
    if meta:
        parts = [str(v) for v in meta.values() if v]
        if parts:
            meta_line = f"<div style='color:#666;font-size:12px;margin-top:-4px;'>{_esc(' · '.join(parts))}</div>"
    return f"<div><h2 style='margin:0 0 4px 0;'>{_esc(ALPHAREQUEST_HEADLINE)}</h2>{meta_line}{ALPHAREQUEST_WARNING_HTML}{inner_html}</div>"


def _truncate_html(html_body: str) -> tuple[str, Optional[str]]:
    """
    Schneidet zu lange HTML-Bodies ab und liefert den Überhang separat zurück
    (z. B. für einen privaten Kommentar).
    """
    if len(html_body) <= MAX_HTML_BODY_LEN:
        return html_body, None
    return html_body[:MAX_HTML_BODY_LEN] + "<p><em>…gekürzt…</em></p>", html_body


def _format_value(key: str, value: Any) -> str:
    """
    Heuristische HTML-Darstellung eines Werts (mit Escaping/Linkify).
    """
    if value in (None, "", []):
        return ""
    k = (key or "").lower()
    if isinstance(value, bool):
        return _esc(_fmt_bool(value))
    if "mail" in k:
        return _linkify(str(value))
    if "url" in k or "link" in k or (isinstance(value, str) and value.startswith("http")):
        return _linkify(str(value))
    if "datum" in k or "date" in k or "time" in k or "beginn" in k:
        return _esc(_fmt_dt(value))
    if isinstance(value, (int, float)):
        return _esc(str(value))
    if isinstance(value, list):
        items = "".join(f"<li>{_linkify(str(x))}</li>" for x in value if str(x).strip())
        return f"<ul style='margin:6px 0 0 18px;'>{items}</ul>"
    # default: Text
    return _linkify(str(value))


def _form_name(form_id: int) -> str:
    return {
        9: "EDV-Zugang beantragen",
        10: "Neue Hardwarebestellung",
        8: "EDV Zugang sperren",
        11: "Niederlassung anmelden",
        12: "Niederlassung umziehen",
        13: "Niederlassung schließen",
    }.get(form_id, f"Form-ID {form_id}")


# =========================================
# EDV-Template (form_id = 9) + Fallback
# =========================================
def _render_generic(desc: Dict[str, Any]) -> str:
    """
    Fallback für unbekannte form_id: einfache Key/Value-Tabelle.
    """
    pairs: list[tuple[str, str]] = []
    for k, v in desc.items():
        label = k.replace("_", " ").title()
        val_html = _format_value(k, v)
        pairs.append((label, val_html))
    return _section("Details", _two_col_table(pairs))


def _render_edv_beantragen(desc: Dict[str, Any]) -> str:
    """
    Spezial-Template für form_id=9 (EDV-Zugang beantragen).
    Erwartete Keys (optional):
      vorname, nachname, firma, arbeitsbeginn, titel,
      strasse, ort, plz, handy, telefon, fax, niederlassung, kostenstelle,
      kommentar, checkbox_datev_user, checkbox_elo_user,
      eloVorgesetzter
    """
    # Kopfblock (Name, Firma, Arbeitsbeginn)
    name = " ".join([str(desc.get("vorname") or ""), str(desc.get("nachname") or "")]).strip()
    firma = desc.get("firma") or ""
    arbeitsbeginn = _fmt_dt(desc.get("arbeitsbeginn"))

    kopf_pairs = []
    if name:
        kopf_pairs.append(("Name", _esc(name)))
    if firma:
        kopf_pairs.append(("Firma", _esc(firma)))
    if arbeitsbeginn:
        kopf_pairs.append(("Arbeitsbeginn", _esc(arbeitsbeginn)))
    kopf_html = _two_col_table(kopf_pairs)

    # Kontaktdaten
    kontakt_pairs = [
        ("Straße", _esc(desc.get("strasse") or "")),
        ("PLZ", _esc(desc.get("plz") or "")),
        ("Ort", _esc(desc.get("ort") or "")),
        ("Telefon", _linkify(desc.get("telefon") or "")),
        ("Handy", _linkify(desc.get("handy") or "")),
        ("Fax", _esc(desc.get("fax") or "")),
        ("Niederlassung", _esc(desc.get("niederlassung") or "")),
        ("Kostenstelle", _esc(desc.get("kostenstelle") or "")),
    ]
    kontakt_html = _two_col_table(kontakt_pairs)

    # Optionen
    elo_checked = bool(desc.get("checkbox_elo_user"))
    elo_vorgesetzter = desc.get("eloVorgesetzter") or ""
    optionen_pairs = [
        ("DATEV-Zugang", _esc(_fmt_bool(desc.get("checkbox_datev_user")))),
        ("ELO-Zugang", _esc(_fmt_bool(elo_checked))),
    ]

    # Zeige "ELO-Vorgesetzter", wenn ELO angehakt ist ODER ein Wert vorhanden ist
    if elo_checked or elo_vorgesetzter:
        optionen_pairs.append(("ELO-Vorgesetzter", _esc(elo_vorgesetzter)))

    optionen_html = _two_col_table(optionen_pairs)

    # Kommentar
    kommentar = desc.get("kommentar") or ""
    kommentar_html = f"<p>{_linkify(kommentar)}</p>" if kommentar else ""

    return "".join([
        _section("Antragsteller", kopf_html),
        _section("Kontaktdaten", kontakt_html),
        _section("Optionen", optionen_html),
        _section("Kommentar", kommentar_html),
    ])

# -------- Hardwarebestellung (form_id = 10) – Alpha-spezifisches Format --------

from datetime import date

def _fmt_date_only(value) -> str:
    """Erwartet 'YYYY-MM-DD' (ohne Uhrzeit) und formatiert 'DD.MM.YYYY'. Fallback: Originalstring."""
    if not value:
        return ""
    try:
        # "2025-10-28"
        if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
            d = date.fromisoformat(value)
            return d.strftime("%d.%m.%Y")
        # Falls mal TS oder ISO mit Zeit reinkommt, nutzen wir die bestehende _fmt_dt:
        return _fmt_dt(value).split(" ")[0]  # nur Datumsteil
    except Exception:
        return str(value)

def _render_hardware_bestellung(desc: dict) -> str:
    """
    Erwartet entweder den Wrapper {"ticketType":"Hardwarebestellung","data":{...}}
    oder direkt das data-Dict mit den exakt von Marco gelieferten Keys.
    """
    d = desc.get("data") if "data" in desc else desc
    d = d or {}

    # 1) Übersicht
    uebersicht_pairs = [
        ("Mitarbeiter-Typ", _esc(d.get("MitarbeiterTyp") or "")),
        ("Name", _esc(d.get("Name") or "")),
        ("Firma", _esc(d.get("Firma") or "")),
        ("Kostenstelle", _esc(d.get("Kostenstelle") or "")),
        ("Lieferung bis", _esc(_fmt_date_only(d.get("Lieferung_bis")))),
    ]
    uebersicht_html = _two_col_table(uebersicht_pairs)

    # 2) Auswahl & Optionen
    artikel = d.get("Artikel") or {}
    # Liste ausgewählter Artikel (nur True)
    gewuenscht = [k for k, v in artikel.items() if bool(v)]
    artikel_html = ""
    if gewuenscht:
        artikel_html = "<ul style='margin:6px 0 0 18px;'>" + "".join(
            f"<li>{_esc(k)}</li>" for k in gewuenscht
        ) + "</ul>"

    geraet = d.get("Geraet") or ""
    dock_vorhanden = d.get("Dockingstation_vorhanden", None)
    monitor = d.get("Monitor") or {}
    monitor_benoetigt = monitor.get("benoetigt", None)
    monitor_anzahl = monitor.get("Anzahl", None)

    auswahl_pairs = [
        ("Gerät", _esc(geraet)),
        ("Ausgewählte Artikel", artikel_html),
        ("Dockingstation vorhanden", "" if dock_vorhanden is None else _esc(_fmt_bool(dock_vorhanden))),
        ("Monitor benötigt", "" if monitor_benoetigt is None else _esc(_fmt_bool(monitor_benoetigt))),
        ("Monitor – Anzahl", "" if not monitor_anzahl else _esc(str(monitor_anzahl))),
    ]
    auswahl_html = _two_col_table(auswahl_pairs)

    # 3) Lieferung
    lieferadresse = d.get("Lieferadresse") or ""
    liefer_pairs = [
        ("Lieferadresse", _linkify(lieferadresse)),
    ]
    liefer_html = _two_col_table(liefer_pairs)

    # 4) Begründung / Bemerkung
    begruendung = d.get("GrundNeubestellung") or ""
    bemerkung = d.get("Bemerkung") or ""
    textteile = []
    if begruendung:
        textteile.append(f"<p><strong>Grund der Neubestellung:</strong><br>{_linkify(str(begruendung))}</p>")
    if bemerkung:
        textteile.append(f"<p><strong>Bemerkung:</strong><br>{_linkify(str(bemerkung))}</p>")
    begruendung_html = "".join(textteile)

    return "".join([
        _section("Übersicht", uebersicht_html),
        _section("Auswahl & Optionen", auswahl_html),
        _section("Lieferung", liefer_html),
        _section("Begründung / Bemerkung", begruendung_html),
    ])

# -------- EDV-Zugang sperren (form_id = 8) – Alpha-spezifisches Format --------
def _pretty_hw_option(v: str) -> str:
    if not v:
        return ""
    x = str(v).strip().lower()
    if x in ("toit", "an_it", "an-it", "it", "zurueck_an_it", "zurück_an_it"):
        return "Hardware an IT zurück"
    if x in ("bleibt", "verbleibt", "remain", "keep"):
        return "Hardware verbleibt beim Mitarbeiter/Standort"
    if x in ("entsorgen", "discard", "dispose"):
        return "Hardware entsorgen"
    if x in ("weitergabe", "uebergabe", "übergabe"):
        return "Hardware an andere Person übergeben"
    return v


def _pretty_daten_aktion(v: str) -> str:
    if not v:
        return ""
    x = str(v).strip().lower()
    if x in ("sichern", "backup", "archiv", "archivieren"):
        return "Daten sichern"
    if x in ("loeschen", "löschen", "delete"):
        return "Daten löschen"
    if x in ("uebertragen", "übertragen", "transfer"):
        return "Daten übertragen"
    return v.capitalize()

def _render_edv_sperren(desc: dict) -> str:
    """
    Erwartet Wrapper oder data-Dict mit Keys:
      benutzer, grund, sperrmodus ('sofort'|'datum'), sperrdatum ('YYYY-MM-DD'),
      mailsWeiterleiten (bool), weiterleitenAn, postfachVollzugriff (bool), vollzugriffFuer,
      abwesenheitAktiv (bool), abwesenheitText,
      datenAktion ('sichern'|'löschen'|'übertragen'), datenBenutzer,
      hardwareOption ('toIT'|'bleibt'|'entsorgen'|'weitergabe'), hardwareWeitergabeName, hardwareBegruendung,
      eloSperren (bool), eloPosition (string)
    """
    d = desc.get("data") if "data" in desc else desc
    d = d or {}

    # --- 1) Überblick ---
    sperrmodus = (d.get("sperrmodus") or "").strip().lower()
    sperrdatum = d.get("sperrdatum") or ""
    sperrzeit_txt = "Sofort" if sperrmodus == "sofort" else (_fmt_date_only(sperrdatum) if sperrdatum else "Zum angegebenen Datum")

    overview_pairs = [
        ("Benutzer", _esc(d.get("benutzer") or "")),
        ("Grund", _linkify(d.get("grund") or "")),
        ("Sperrzeitpunkt", _esc(sperrzeit_txt)),
    ]
    overview_html = _two_col_table(overview_pairs)

    # --- 2) E-Mail & Postfach ---
    mails_wl = d.get("mailsWeiterleiten")
    wl_an = d.get("weiterleitenAn") or ""
    vollzugriff = d.get("postfachVollzugriff")
    vollzugriff_fuer = d.get("vollzugriffFuer") or ""

    mail_pairs = [
        ("E-Mails weiterleiten", _esc(_fmt_bool(mails_wl)) if mails_wl is not None else ""),
        ("Weiterleiten an", _linkify(wl_an) if mails_wl else ""),
        ("Postfach: Vollzugriff gewähren", _esc(_fmt_bool(vollzugriff)) if vollzugriff is not None else ""),
        ("Vollzugriff für", _esc(vollzugriff_fuer) if vollzugriff else ""),
    ]
    mail_html = _two_col_table(mail_pairs)

    # --- 3) Abwesenheit ---
    abw_aktiv = d.get("abwesenheitAktiv")
    abw_text = d.get("abwesenheitText") or ""
    abw_pairs = [
        ("Abwesenheitsnotiz aktiv", _esc(_fmt_bool(abw_aktiv)) if abw_aktiv is not None else ""),
        ("Abwesenheitstext", _linkify(abw_text) if abw_aktiv else ""),
    ]
    abw_html = _two_col_table(abw_pairs)

    # --- 4) Datenhandling ---
    aktion = _pretty_daten_aktion(d.get("datenAktion"))
    daten_user = d.get("datenBenutzer") or ""
    daten_pairs = [
        ("Aktion für Benutzerdaten", _esc(aktion)),
        ("Daten übertragen an", _esc(daten_user) if (str(d.get("datenAktion") or "").strip().lower() in ("uebertragen", "übertragen", "transfer")) else ""),
    ]
    daten_html = _two_col_table(daten_pairs)

    # --- 5) ELO ---
    elo_sperren = d.get("eloSperren")
    elo_pos = d.get("eloPosition") or ""
    elo_pairs = [
        ("ELO-Zugang sperren", _esc(_fmt_bool(elo_sperren)) if elo_sperren is not None else ""),
        ("ELO-Position", _esc(elo_pos) if elo_sperren else ""),
    ]
    elo_html = _two_col_table(elo_pairs)

    # --- 6) Hardware ---
    hw_opt_raw = d.get("hardwareOption")
    hw_opt = _pretty_hw_option(hw_opt_raw)
    hw_name = d.get("hardwareWeitergabeName") or ""
    hw_begr = d.get("hardwareBegruendung") or ""
    hw_pairs = [
        ("Hardware-Option", _esc(hw_opt)),
        ("Weitergabe an", _esc(hw_name) if str(hw_opt_raw or "").strip().lower() in ("weitergabe", "uebergabe", "übergabe") else ""),
        ("Begründung (Hardware)", _linkify(hw_begr)),
    ]
    hw_html = _two_col_table(hw_pairs)

    return "".join([
        _section("Überblick", overview_html),
        _section("E-Mail & Postfach", mail_html),
        _section("Abwesenheit", abw_html),
        _section("Daten", daten_html),
        _section("ELO", elo_html),
        _section("Hardware", hw_html),
    ])

# -------- Niederlassung anmelden (form_id = 11) – Alpha-spezifisches Format --------
def _render_niederlassung_anmelden(desc: dict) -> str:
    """
    Erwartet entweder Wrapper:
      {"ticketType":"Niederlassung anmelden","data":{...}}
    oder direkt das data-Dict mit folgenden Keys:
      ort, strasse, plz, firma, startDatum (YYYY-MM-DD), leiter, mitarbeiter,
      kostenstelle, tuerSchild (bool), hardwareEmpfang, bemerkung
    """
    d = desc.get("data") if "data" in desc else desc
    d = d or {}

    # 1) Standort / Firma
    standort_pairs = [
        ("Firma", _esc(d.get("firma") or "")),
        ("Straße", _esc(d.get("strasse") or "")),
        ("PLZ", _esc(d.get("plz") or "")),
        ("Ort", _esc(d.get("ort") or "")),
        ("Startdatum", _esc(_fmt_date_only(d.get("startDatum")))),
    ]
    standort_html = _two_col_table(standort_pairs)

    # 2) Verantwortliche & Organisation
    org_pairs = [
        ("Niederlassungsleiter:in", _esc(d.get("leiter") or "")),
        ("Mitarbeiter (Anzahl)", _esc(str(d.get("mitarbeiter") or ""))),
        ("Kostenstelle", _esc(d.get("kostenstelle") or "")),
        ("Türschild vorhanden", _esc(_fmt_bool(d.get("tuerSchild"))) if d.get("tuerSchild") is not None else ""),
        ("Hardware-Empfang durch", _esc(d.get("hardwareEmpfang") or "")),
    ]
    org_html = _two_col_table(org_pairs)

    # 3) Bemerkung (optional)
    bemerkung = d.get("bemerkung") or ""
    bemerkung_html = f"<p>{_linkify(bemerkung)}</p>" if bemerkung else ""

    return "".join([
        _section("Standort", standort_html),
        _section("Organisation", org_html),
        _section("Bemerkung", bemerkung_html),
    ])

# -------- Niederlassung umziehen (form_id = 12) – Alpha-spezifisches Format --------
def _render_niederlassung_umziehen(desc: dict) -> str:
    """
    Erwartet entweder Wrapper:
      {"ticketType":"Niederlassung umziehen","data":{...}}
    oder direkt das data-Dict mit folgenden Keys:
      firma, kostenstelle, aktuell, neu, datum (YYYY-MM-DD), mitarbeiterNeu,
      portierung (bool), kontakt, bemerkung
    """
    d = desc.get("data") if "data" in desc else desc
    d = d or {}

    # 1) Überblick
    overview_pairs = [
        ("Firma", _esc(d.get("firma") or "")),
        ("Kostenstelle", _esc(d.get("kostenstelle") or "")),
        ("Umzugsdatum", _esc(_fmt_date_only(d.get("datum")))),
        ("Mitarbeiter (neu)", _esc(str(d.get("mitarbeiterNeu") or ""))),
    ]
    overview_html = _two_col_table(overview_pairs)

    # 2) Standorte
    standort_pairs = [
        ("Bisherige Adresse", _linkify(d.get("aktuell") or "")),
        ("Neue Adresse", _linkify(d.get("neu") or "")),
    ]
    standort_html = _two_col_table(standort_pairs)

    # 3) Telefonie / Portierung
    tel_pairs = [
        ("Rufnummern-Portierung gewünscht", _esc(_fmt_bool(d.get("portierung"))) if d.get("portierung") is not None else ""),
        ("Kontaktperson", _linkify(d.get("kontakt") or "")),
    ]
    tel_html = _two_col_table(tel_pairs)

    # 4) Bemerkung (optional)
    bemerkung = d.get("bemerkung") or ""
    bemerkung_html = f"<p>{_linkify(bemerkung)}</p>" if bemerkung else ""

    return "".join([
        _section("Überblick", overview_html),
        _section("Standorte", standort_html),
        _section("Telefonie", tel_html),
        _section("Bemerkung", bemerkung_html),
    ])

# -------- Niederlassung schließen (form_id = 13) – Alpha-spezifisches Format --------
def _pretty_hw_action(v: str) -> str:
    if not v:
        return ""
    x = str(v).strip().lower()
    if x in ("toit", "an_it", "an-it", "it"):
        return "Hardware an IT zurück"
    if x in ("bleibt", "verbleibt", "remain", "keep"):
        return "Hardware verbleibt vor Ort"
    if x in ("entsorgen", "discard", "dispose"):
        return "Hardware entsorgen"
    if x in ("transfer", "uebertragen", "übertragen", "move"):
        return "Hardware zu anderer Niederlassung"
    return v  # Fallback: Rohwert anzeigen

def _render_niederlassung_schliessen(desc: dict) -> str:
    """
    Erwartet entweder Wrapper:
      {"ticketType":"Niederlassung schließen","data":{...}}
    oder direkt das data-Dict mit Keys:
      firma, niederlassung, aktuell, schliessung (YYYY-MM-DD),
      bemerkung, dslKuendigung (bool), rufnummerKuendigung (bool),
      hardware (z.B. 'toIT'/'bleibt'/'entsorgen'/'transfer'), targetNL
    """
    d = desc.get("data") if "data" in desc else desc
    d = d or {}

    # 1) Überblick
    overview_pairs = [
        ("Firma", _esc(d.get("firma") or "")),
        ("Niederlassung", _esc(d.get("niederlassung") or "")),
        ("Schließungsdatum", _esc(_fmt_date_only(d.get("schliessung")))),
    ]
    overview_html = _two_col_table(overview_pairs)

    # 2) Standort
    standort_pairs = [
        ("Aktuelle Adresse", _linkify(d.get("aktuell") or "")),
    ]
    standort_html = _two_col_table(standort_pairs)

    # 3) Infrastruktur (Provider/Telefonie)
    infra_pairs = [
        ("DSL kündigen", _esc(_fmt_bool(d.get("dslKuendigung"))) if d.get("dslKuendigung") is not None else ""),
        ("Rufnummern kündigen", _esc(_fmt_bool(d.get("rufnummerKuendigung"))) if d.get("rufnummerKuendigung") is not None else ""),
    ]
    infra_html = _two_col_table(infra_pairs)

    # 4) Hardware / Inventar
    hw_action = _pretty_hw_action(d.get("hardware"))
    target_nl = d.get("targetNL") or ""
    hw_pairs = [
        ("Hardware-Aktion", _esc(hw_action)),
        ("Ziel-Niederlassung", _esc(target_nl) if hw_action.startswith("Hardware zu") or target_nl else ""),
    ]
    hw_html = _two_col_table(hw_pairs)

    # 5) Bemerkung (optional)
    bemerkung = d.get("bemerkung") or ""
    bemerkung_html = f"<p>{_linkify(bemerkung)}</p>" if bemerkung else ""

    return "".join([
        _section("Überblick", overview_html),
        _section("Standort", standort_html),
        _section("Infrastruktur", infra_html),
        _section("Hardware / Inventar", hw_html),
        _section("Bemerkung", bemerkung_html),
    ])


def _pick_renderer(form_id: int):
    return {
        9: _render_edv_beantragen,
        10: _render_hardware_bestellung,
        8: _render_edv_sperren,
        11: _render_niederlassung_anmelden,
        12: _render_niederlassung_umziehen,
        13: _render_niederlassung_schliessen,
    }.get(form_id, _render_generic)


# =========================================
# Zentrale Render-Funktion
# =========================================
def render_ticket_description(form_id: int, description: str | dict, *, prefill: dict | None = None):
    # --- String-Fall bleibt wie gehabt ---
    if not isinstance(description, dict):
        body_text = str(description or "").strip()
        html_inner = f"<p>{_linkify(body_text)}</p>"
        html = _wrap_base(html_inner, meta={"form": _form_name(form_id)})
        html, overflow = _truncate_html(html)
        return {"public": True, "body": body_text, "htmlBody": html}, overflow

    # --- NEU: desc_obj-Wrapper unterstützen: {"ticketType": "...", "data": {...}} ---
    # Wenn so ein Wrapper kommt, entpacken wir ihn und mappen EDV-spezifische Felder.
    if "ticketType" in description and "data" in description:
        ticket_type = description.get("ticketType")
        data = description.get("data") or {}

        # EDV-Zugang: booleans & ggf. Feldnamen mappen
        if ticket_type == "EDV-Zugang beantragen":
            desc = dict(data)
            # Erwartete EDV-Schlüssel setzen/ableiten:
            desc["checkbox_datev_user"] = bool(data.get("datev"))
            desc["checkbox_elo_user"] = bool(data.get("elo"))
        else:
            # generisch: nimm einfach den data-Block
            desc = dict(data)
    else:
        # alter Pfad: description ist bereits das Daten-Dict
        desc = dict(description)

    # Prefill (aus Attributes) reinmergen – description gewinnt bei Kollision:
    if prefill:
        for k, v in prefill.items():
            desc.setdefault(k, v)

    # Ab hier wie gehabt:
    renderer = _pick_renderer(form_id)
    inner_html = renderer(desc)

    # Kurztext für Body:
    body_bits = []
    if form_id == 9:
        nm = " ".join([str(desc.get("vorname") or ""), str(desc.get("nachname") or "")]).strip()
        firma = desc.get("firma") or ""
        ab = _fmt_dt(desc.get("arbeitsbeginn"))
        body_bits = [bit for bit in [nm, firma, ab] if bit]
    body_text = " · ".join(body_bits) if body_bits else "Siehe Details."

    html = _wrap_base(inner_html, meta={"form": _form_name(form_id)})
    html, overflow = _truncate_html(html)
    return {"public": True, "body": body_text, "htmlBody": html}, overflow
