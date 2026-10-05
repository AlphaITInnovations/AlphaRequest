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

/** Widgets, deren Wert ein String sein muss (Spiegel von _STRING_WIDGETS). */
const STRING_WIDGETS = ['text', 'textarea', 'date']

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

/** Prefill-Wert eines select-Feldes auf einen Options-Wert abbilden (Directus
 *  liefert evtl. Label/andere Schreibweise). Spiegel von _match_option; ohne
 *  Treffer (und ohne allowOther) undefined → das Feld bleibt leer statt ungültig.
 *  Exportiert, weil auch das Live-Auto-Fill der directus-Auswahl (SchemaForm
 *  coerceForTarget) ein select-Ziel so vorwählen muss. */
export function matchOption(val: unknown, f: FieldDef): unknown {
  if (val === undefined || val === null || val === '' || !f.options?.length) return val
  const s = String(val).trim().toLocaleLowerCase()
  for (const opt of f.options) {
    if (String(opt.value).trim().toLocaleLowerCase() === s) return opt.value
    if (opt.label && String(opt.label).trim().toLocaleLowerCase() === s) return opt.value
  }
  return f.allowOther ? val : undefined
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
    const raw = resolvePath(src, f.prefill.field)
    let val: unknown
    if (f.widget === 'directus') {
      // Directus-Fremdschlüssel: die ROH-ID (nicht den Anzeigenamen) und als
      // String – die Wert-Prüfung erwartet für directus eine Text-ID.
      const rid = raw && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Record<string, unknown>).id : raw
      val = (rid === null || rid === undefined || rid === '') ? rid : String(rid)
    } else {
      val = displayValue(raw)
      if (f.widget === 'select') val = matchOption(val, f)
      // Text-Widgets brauchen einen String – eine Directus-Zahl (id, PLZ,
      // Personalnummer) würde sonst als „Text erwartet" verworfen.
      if (typeof val === 'number' && STRING_WIDGETS.includes(f.widget)) val = String(val)
    }
    if (val !== undefined && val !== null && val !== '') out[f.key] = val
  }
  return out
}
