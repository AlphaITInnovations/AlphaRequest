/**
 * Vorbelegung von Feldern aus den Daten der angemeldeten Person (Spiegel von
 * services/process_prefill.apply_prefill). Nur für die Anzeige beim Anlegen –
 * autoritativ setzt der Server die Werte erneut.
 */
import type { FieldDef } from '@/types/process'

type Values = Record<string, unknown>

function resolvePath(obj: unknown, path: string): unknown {
  let cur: unknown = obj
  for (const part of path.split('.')) {
    if (cur && typeof cur === 'object' && !Array.isArray(cur)) {
      cur = (cur as Record<string, unknown>)[part]
    } else {
      return undefined
    }
  }
  return cur
}

const DISPLAY_FIELDS = ['name', 'label', 'title', 'bezeichnung', 'nummer']

/** Relation (Objekt) → Name/Label, Liste → verbundene Werte, Skalar bleibt.
 *  Spiegel von process_prefill._display_value; verhindert „[object Object]". */
function displayValue(v: unknown): unknown {
  if (Array.isArray(v)) {
    const parts = v.map(displayValue).filter((x) => x !== undefined && x !== null && x !== '')
    return parts.length ? parts.join(', ') : undefined
  }
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    for (const k of DISPLAY_FIELDS) {
      if (typeof o[k] === 'string' || typeof o[k] === 'number') return o[k]
    }
    return undefined
  }
  return v
}

/** `profile` = Antwort von /auth/profile (employee + Konto-Felder wie phone/email). */
export function applyPrefill(
  fields: FieldDef[], profile: Record<string, unknown> | null, values: Values,
): Values {
  const out: Values = { ...values }
  const employee = (profile?.employee as Record<string, unknown>) ?? {}
  for (const f of fields) {
    if (!f.prefill?.field) continue
    const src = f.prefill.source === 'user' ? (profile ?? {}) : employee
    const val = displayValue(resolvePath(src, f.prefill.field))
    if (val !== undefined && val !== null && val !== '') out[f.key] = val
  }
  return out
}
