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
    if (cur && typeof cur === 'object') cur = (cur as Record<string, unknown>)[part]
    else return undefined
  }
  return cur
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
    const val = resolvePath(src, f.prefill.field)
    // Nur Skalare: eine nicht aufgelöste Relation (Objekt/Array) darf nicht als
    // Wert landen (sonst „[object Object]"). Pfad auf ein Unterfeld zeigen lassen.
    if (val !== undefined && val !== null && val !== '' && typeof val !== 'object') {
      out[f.key] = val
    }
  }
  return out
}
