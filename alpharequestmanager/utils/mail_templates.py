# alpharequestmanager/mail_templates.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import html


@dataclass
class MailBranding:
    company_name: str = "Alpha-IT-Innovations"

    # Brand
    primary_color: str = "#3EACB6"
    primary_dark: str = "#084C59"
    text_color: str = "#101924"
    muted_text: str = "#4B5563"
    background: str = "#ECF7F8"
    surface: str = "#FFFFFF"
    border: str = "#CFE9EC"

    footer_text: str = "Diese E-Mail wurde automatisch generiert."
    logo_cid: str = "alpha_logo"


BASE_TEMPLATE = """\
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="x-apple-disable-message-reformatting">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background:{bg};">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:{bg};">
    <tr>
      <td align="center" style="padding:26px 12px;">

        <table role="presentation" cellpadding="0" cellspacing="0" width="600"
               style="width:600px; max-width:600px; background:{surface}; border-radius:16px; overflow:hidden; border:1px solid {border};
                      box-shadow:0 10px 26px rgba(16,25,36,0.10);">

          <tr>
            <td style="height:6px; background:{primary}; line-height:6px; font-size:0;">&nbsp;</td>
          </tr>

          <tr>
            <td style="padding:18px 20px 12px 20px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td valign="middle" style="width:56px;">
                    <img src="cid:{logo_cid}" width="44" height="44" alt="{company_name}"
                         style="display:block; border-radius:12px; background:#ffffff; border:1px solid {border}; padding:6px;">
                  </td>
                  <td valign="middle" style="padding-left:12px;">
                    <div style="font-family:Arial,Helvetica,sans-serif; color:{text}; font-size:16px; font-weight:700; line-height:1.2;">
                      {company_name}
                    </div>
                    <div style="font-family:Arial,Helvetica,sans-serif; color:{muted}; font-size:12px; line-height:1.4; padding-top:3px;">
                      {header_subtitle}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:10px 22px 8px 22px;">

              {headline_html}

              <div style="font-family:Arial,Helvetica,sans-serif; color:{text}; font-size:14px; line-height:1.7; padding-top:12px;">
                {intro_html}
              </div>

              <div style="font-family:Arial,Helvetica,sans-serif; color:{text}; font-size:14px; line-height:1.75; padding-top:14px;">
                {content_html}
              </div>

              <div style="padding-top:16px; border-top:1px solid {border}; margin-top:18px;"></div>
            </td>
          </tr>

          <tr>
            <td style="padding:14px 22px 20px 22px;">
              <div style="font-family:Arial,Helvetica,sans-serif; color:{muted}; font-size:12px; line-height:1.6;">
                {footer_text}
              </div>
              <div style="font-family:Arial,Helvetica,sans-serif; color:{muted}; opacity:0.85; font-size:11px; line-height:1.6; padding-top:6px;">
                {legal_hint}
              </div>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>
</body>
</html>
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_corporate_email(
    *,
    subject: str,
    headline: str,
    intro: str,
    content: str,
    branding: Optional[MailBranding] = None,
    header_subtitle: str = "Automatisierte Benachrichtigung",
    info_box_url: Optional[str] = None,  # HEADLINE link
    footer_text: Optional[str] = None,
    legal_hint: str = "Bitte nicht auf diese E-Mail antworten, sofern nicht anders angegeben.",
) -> str:
    """
    Corporate email template.

    Changes (per request):
    - info_box_* removed entirely
    - headline is clickable and opens info_box_url (required)
    """
    b = branding or MailBranding()

    if not info_box_url:
        raise ValueError("info_box_url ist Pflicht (Headline soll klickbar sein).")

    intro_html = _esc(intro).replace("\n", "<br>")
    content_html = _esc(content).replace("\n", "<br>")
    href = _esc(info_box_url)

    # Clickable headline (bigger; looks like headline, not blue underlined link)
    headline_html = f"""
    <div style="padding-top:2px;">
      <a href="{href}"
         style="font-family:Arial,Helvetica,sans-serif; color:{b.text_color}; font-size:20px; font-weight:800; line-height:1.25;
                text-decoration:none; display:inline-block;">
        {_esc(headline)}
      </a>
    </div>
    """

    return BASE_TEMPLATE.format(
        subject=_esc(subject),
        bg=b.background,
        surface=b.surface,
        border=b.border,
        primary=b.primary_color,
        text=b.text_color,
        muted=b.muted_text,
        company_name=_esc(b.company_name),
        logo_cid=_esc(b.logo_cid),
        header_subtitle=_esc(header_subtitle),
        headline_html=headline_html,
        intro_html=intro_html,
        content_html=content_html,
        footer_text=_esc(footer_text or b.footer_text),
        legal_hint=_esc(legal_hint),
    )
