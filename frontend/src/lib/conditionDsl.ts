/**
 * Frontend-Spiegel der Condition-DSL (§6.1) und der Wert-Ausdrücke (§3.1).
 *
 * MUSS mit dem autoritativen Backend übereinstimmen:
 *   - Bedingungen: backend/services/condition_dsl.py (evaluate)
 *   - computed:    backend/services/process_compute.py (apply_computed)
 * Das Backend bleibt maßgeblich (Sicherheit/Pflicht); dieser Spiegel dient nur
 * der Live-UX im Formular-Renderer/Editor (Felder ein-/ausblenden, Pflicht
 * markieren, abgeleitete Werte anzeigen).
 */

export type Values = Record<string, unknown>
export type Condition = Record<string, any>

/** Wertet einen (wohlgeformten) DSL-Ausdruck gegen die Feldwerte aus. */
export function evaluate(cond: Condition | null | undefined, values: Values): boolean {
  if (!cond || typeof cond !== 'object' || Array.isArray(cond)) return false
  const keys = Object.keys(cond)
  if (keys.length !== 1) return false
  const op = keys[0]
  const arg = cond[op]
  switch (op) {
    case '==':
      return Array.isArray(arg) && values[arg[0]] === arg[1]
    case '!=':
      return Array.isArray(arg) && values[arg[0]] !== arg[1]
    case 'in':
      return Array.isArray(arg) && Array.isArray(arg[1]) && arg[1].includes(values[arg[0]] as never)
    case 'truthy':
      return typeof arg === 'string' && !!values[arg]
    case 'and':
      return Array.isArray(arg) && arg.every((c) => evaluate(c, values))
    case 'or':
      return Array.isArray(arg) && arg.some((c) => evaluate(c, values))
    case 'not':
      return !evaluate(arg, values)
    default:
      return false
  }
}

export function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === '' ||
    (Array.isArray(v) && v.length === 0) ||
    (typeof v === 'object' && v !== null && !Array.isArray(v) && Object.keys(v).length === 0)
}

export interface ComputedFieldDef {
  key: string
  computed?: { from: string } | null
  overridable?: boolean
}

/**
 * Füllt computed-Felder (Spiegel von process_compute.apply_computed):
 *  - non-overridable → immer aus der Quelle,
 *  - overridable     → nur wenn Ziel leer (manuell gesetzter Wert bleibt).
 */
export function applyComputed(fields: ComputedFieldDef[], values: Values): Values {
  const out: Values = { ...values }
  for (const f of fields) {
    if (!f.computed) continue
    const src = out[f.computed.from]
    if (f.overridable) {
      if (isEmpty(out[f.key]) && !isEmpty(src)) out[f.key] = src
    } else {
      out[f.key] = src
    }
  }
  return out
}
