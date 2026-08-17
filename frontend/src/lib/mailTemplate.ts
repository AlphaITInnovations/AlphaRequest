/**
 * Ticket-Variablen in Mail-Vorlagen (`{{feld.key}}`). Spiegelt
 * backend/services/mail_template.py – Regex und Spezial-Variablen müssen
 * übereinstimmen, sonst warnt der Editor anders als der Server validiert.
 *
 * Hier NUR das Erkennen der Variablen (fürs Einfügen im Editor und die
 * Validierung). Ersetzt wird ausschließlich serverseitig beim Mailversand.
 */

/** `{{ feld.key }}` – Feld-Keys sind a-z0-9_ mit Punkten (base.first_name). */
export const MAIL_VAR_RE = /\{\{\s*([A-Za-z0-9_.]+)\s*\}\}/g

/** Variablen, die kein Katalog-Feld sind, aber immer verfügbar. */
export const SPECIAL_MAIL_VARS = ['title', 'id'] as const

/** Alle vorkommenden Variablen, ohne Dopplungen, in Reihenfolge. */
export function mailVariables(text: string | null | undefined): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const m of (text ?? '').matchAll(MAIL_VAR_RE)) {
    if (!seen.has(m[1])) { seen.add(m[1]); out.push(m[1]) }
  }
  return out
}

/** Nur die Variablen, die ein Katalog-Feld referenzieren (ohne Spezial-Vars). */
export function mailFieldRefs(text: string | null | undefined): string[] {
  return mailVariables(text).filter((v) => !SPECIAL_MAIL_VARS.includes(v as any))
}
