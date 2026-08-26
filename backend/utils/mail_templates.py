# backend/utils/mail_templates.py
"""Modernes, cleanes Mail-Layout im AlphaRequest-Corporate-Design.

Ein einziges Template für ALLE System-Mails (Neue Aufgabe, Freigabe, Erinnerung,
Nachtrag, Ablehnung, Nachbesserung, Feedback …). Die Aufrufer liefern nur Inhalt
(Headline, Intro, Fakten, Aktions-Buttons); Aussehen und Struktur stehen nur hier.

Mail-Realität, bewusst berücksichtigt:
  * Tabellen-Layout + Inline-Styles (Outlook/Word-Engine kann kein Flexbox/CSS-Grid,
    ignoriert `border-radius`/`box-shadow` – degradiert sauber zu eckig).
  * System-Font-Stack mit Arial-Fallback.
  * Logo als `cid:alpha_logo` (Inline-Anhang, siehe microsoft_mail.brand_logo_attachment).
  * Werte kommen aus Nutzereingaben → alles wird escaped; `action_html` ist der
    EINZIGE Roh-HTML-Slot (Buttons/Zitat-Blöcke, von den Aufrufern selbst escaped).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from backend.utils.config import config

#: System-Font-Stack – modern auf allen Clients, Arial als sicherer Fallback.
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
        "'Apple Color Emoji','Segoe UI Emoji',sans-serif")


@dataclass
class MailBranding:
    company_name: str = "AlphaRequest"
    legal_name: str = "Alpha-IT-Innovations"

    # Türkis-Palette der App (Sidebar/Buttons: #3EAAB8) + ruhige, neutrale Flächen.
    primary_color: str = "#3EAAB8"
    primary_dark: str = "#2B7D89"
    heading_color: str = "#0F1B24"   # Überschriften / kräftige Werte
    text_color: str = "#3A4754"      # Fließtext
    muted_text: str = "#6B7885"      # Labels, Fußzeile
    faint_text: str = "#95A2AC"      # feinste Hinweise
    background: str = "#EDF1F3"      # Seitenhintergrund hinter der Karte
    surface: str = "#FFFFFF"         # Karte
    surface_subtle: str = "#F5F8FA"  # Info-Karte / Zitat-Block
    border: str = "#E5EBEE"          # Karten-/Trennlinien

    footer_text: str = "Automatisch von AlphaRequest gesendet."
    logo_cid: str = "alpha_logo"


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _multiline(s: str) -> str:
    """Escapen und Zeilenumbrüche zu <br> – für Fließtext aus Nutzereingaben."""
    return _esc(s).replace("\n", "<br>")


def render_corporate_email(
    *,
    subject: str,
    headline: str,
    intro: str = "",
    content: str = "",
    branding: Optional[MailBranding] = None,
    header_subtitle: str = "Benachrichtigung",
    info_box_url: Optional[str] = None,          # macht die Headline klickbar (optional)
    info_rows: Optional[Sequence[Tuple[str, str]]] = None,   # (Label, Wert)-Fakten
    footer_text: Optional[str] = None,
    legal_hint: str = "Bitte nicht auf diese E-Mail antworten.",
    action_html: str = "",                       # ROH-HTML (Buttons/Zitat) – NICHT escaped
) -> str:
    """Rendert eine System-Mail im Corporate-Design.

    - `header_subtitle` steht als kleines Eyebrow-Label (türkis, versal) über der
      Headline und benennt den Anlass (z. B. „Freigabe erforderlich").
    - `headline` ist mit `info_box_url` klickbar, sonst reiner Text (z. B. für
      Freigabe-Mails an externe Empfänger:innen ohne Systemzugang).
    - `info_rows` rendern eine ruhige Fakten-Karte (Label/Wert).
    - In Nicht-Produktionsumgebungen erscheint ein dezentes TEST-Band.
    """
    b = branding or MailBranding()

    # ── Eyebrow (Anlass) ──────────────────────────────────────────────────────
    eyebrow_html = ""
    if header_subtitle:
        eyebrow_html = (
            f'<div style="font-family:{FONT}; color:{b.primary_dark}; font-size:12px; '
            f'font-weight:700; letter-spacing:1.2px; text-transform:uppercase; '
            f'padding-bottom:8px;">{_esc(header_subtitle)}</div>')

    # ── Headline (klickbar oder Text) ─────────────────────────────────────────
    hl_style = (f"font-family:{FONT}; color:{b.heading_color}; font-size:23px; "
                "font-weight:700; line-height:1.3; text-decoration:none; margin:0;")
    if info_box_url:
        headline_html = f'<a href="{_esc(info_box_url)}" style="{hl_style}">{_esc(headline)}</a>'
    else:
        headline_html = f'<div style="{hl_style}">{_esc(headline)}</div>'

    # ── Intro / Content ───────────────────────────────────────────────────────
    para = (f"font-family:{FONT}; color:{b.text_color}; font-size:15px; "
            "line-height:1.65; margin:0;")
    intro_html = (f'<div style="{para} padding-top:14px;">{_multiline(intro)}</div>'
                  if intro and intro.strip() else "")
    content_html = (f'<div style="{para} padding-top:14px;">{_multiline(content)}</div>'
                    if content and content.strip() else "")

    # ── Fakten-Karte (Label/Wert) ─────────────────────────────────────────────
    info_html = ""
    if info_rows:
        cells = []
        for i, (label, value) in enumerate(info_rows):
            sep = (f"border-top:1px solid {b.border};" if i else "")
            cells.append(
                f'<tr>'
                f'<td style="font-family:{FONT}; color:{b.muted_text}; font-size:13px; '
                f'padding:10px 14px 10px 0; white-space:nowrap; vertical-align:top; {sep}">'
                f'{_esc(label)}</td>'
                f'<td style="font-family:{FONT}; color:{b.heading_color}; font-size:14px; '
                f'font-weight:600; padding:10px 0; vertical-align:top; text-align:right; {sep}">'
                f'{_multiline(value)}</td>'
                f'</tr>')
        info_html = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
            f'style="margin-top:20px; background:{b.surface_subtle}; border:1px solid {b.border}; '
            f'border-radius:12px;"><tr><td style="padding:4px 16px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">'
            f'{"".join(cells)}</table></td></tr></table>')

    # ── TEST-Band (nur außerhalb Produktion) ──────────────────────────────────
    dev_banner = ""
    env = (config.APP_ENV or "").strip()
    if env.lower() != "production":
        dev_banner = (
            f'<tr><td style="background:#FEF3C7; padding:10px 32px; '
            f'border-bottom:1px solid #FCE4A6;">'
            f'<div style="font-family:{FONT}; color:#92610A; font-size:12px; '
            f'font-weight:700; letter-spacing:0.3px;">TESTUMGEBUNG '
            f'({_esc(env.upper() or "DEV")}) &middot; keine echte Benachrichtigung</div>'
            f'</td></tr>')

    return BASE_TEMPLATE.format(
        subject=_esc(subject),
        font=FONT,
        bg=b.background,
        surface=b.surface,
        border=b.border,
        primary=b.primary_color,
        heading=b.heading_color,
        muted=b.muted_text,
        faint=b.faint_text,
        company_name=_esc(b.company_name),
        legal_name=_esc(b.legal_name),
        logo_cid=_esc(b.logo_cid),
        dev_banner=dev_banner,
        eyebrow_html=eyebrow_html,
        headline_html=headline_html,
        intro_html=intro_html,
        info_html=info_html,
        content_html=content_html,
        action_html=action_html or "",
        footer_text=_esc(footer_text or b.footer_text),
        legal_hint=_esc(legal_hint),
    )


BASE_TEMPLATE = """\
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="color-scheme" content="light only">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background:{bg}; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; opacity:0;">{subject}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:{bg};">
    <tr>
      <td align="center" style="padding:32px 12px;">

        <table role="presentation" cellpadding="0" cellspacing="0" width="600"
               style="width:600px; max-width:600px; background:{surface}; border-radius:16px;
                      overflow:hidden; border:1px solid {border};">

          {dev_banner}

          <!-- Header -->
          <tr>
            <td style="padding:28px 32px 20px 32px; border-bottom:1px solid {border};">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td valign="middle" style="width:40px;">
                    <img src="cid:{logo_cid}" width="36" height="36" alt="{company_name}"
                         style="display:block;">
                  </td>
                  <td valign="middle" style="padding-left:12px; font-family:{font};
                             color:{heading}; font-size:18px; font-weight:700; letter-spacing:-0.2px;">
                    {company_name}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              {eyebrow_html}
              {headline_html}
              {intro_html}
              {info_html}
              {content_html}
              {action_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 32px 28px 32px;">
              <div style="border-top:1px solid {border}; padding-top:18px;">
                <div style="font-family:{font}; color:{muted}; font-size:13px; line-height:1.6;">
                  {footer_text}
                </div>
                <div style="font-family:{font}; color:{faint}; font-size:12px; line-height:1.6; padding-top:4px;">
                  {legal_hint}
                </div>
              </div>
            </td>
          </tr>

        </table>

        <!-- Brand-Zeile unter der Karte -->
        <table role="presentation" cellpadding="0" cellspacing="0" width="600" style="width:600px; max-width:600px;">
          <tr>
            <td align="center" style="padding:16px 12px 0 12px; font-family:{font};
                       color:{faint}; font-size:12px; line-height:1.5;">
              {company_name} &middot; {legal_name}
            </td>
          </tr>
        </table>

      </td>
    </tr>
  </table>
</body>
</html>
"""
