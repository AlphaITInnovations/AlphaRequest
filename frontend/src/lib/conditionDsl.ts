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

/** Python-Truthiness (bool()): None/undefined, false, 0, '', [], {} sind falsy. */
function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined) return false
  if (typeof v === 'boolean') return v
  if (typeof v === 'number') return v !== 0
  if (typeof v === 'string') return v.length > 0
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return !!v
}

/** Python-Gleichheit für JSON-Werte: fehlender Key = null; Listen/Objekte wertgleich. */
function pyEq(a: unknown, b: unknown): boolean {
  const x = a === undefined ? null : a
  const y = b === undefined ? null : b
  if (x === null || y === null || typeof x !== 'object' || typeof y !== 'object') return x === y
  return JSON.stringify(x) === JSON.stringify(y)
}

/** Wertet einen (wohlgeformten) DSL-Ausdruck aus – deckungsgleich mit condition_dsl.py. */
export function evaluate(cond: Condition | null | undefined, values: Values): boolean {
  if (!cond || typeof cond !== 'object' || Array.isArray(cond)) return false
  const keys = Object.keys(cond)
  if (keys.length !== 1) return false
  const op = keys[0]
  const arg = cond[op]
  switch (op) {
    case '==':
      return Array.isArray(arg) && pyEq(values[arg[0]], arg[1])
    case '!=':
      return Array.isArray(arg) && !pyEq(values[arg[0]], arg[1])
    case 'in':
      return Array.isArray(arg) && Array.isArray(arg[1]) &&
        arg[1].some((el) => pyEq(el, values[arg[0]]))
    case 'truthy':
      return typeof arg === 'string' && pyTruthy(values[arg])
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
  computed?: { from: string; map?: Record<string, unknown> | null } | null
  overridable?: boolean
}

/**
 * Füllt computed-Felder (Spiegel von process_compute.apply_computed):
 *  - non-overridable → immer aus der Quelle,
 *  - overridable     → nur wenn Ziel leer (manuell gesetzter Wert bleibt).
 * Mit `computed.map` wird der Quellwert übersetzt (z. B. Position →
 * Fahrzeuggruppe); ein nicht enthaltener Quellwert ergibt null.
 */
export function applyComputed(fields: ComputedFieldDef[], values: Values): Values {
  const out: Values = { ...values }
  const computed = fields.filter((f) => f.computed)
  for (let i = 0; i <= computed.length; i++) {
    let changed = false
    for (const f of computed) {
      const src = out[f.computed!.from]
      const m = f.computed!.map
      // Exakt wie das Backend (process_compute.apply_computed): map.get(src) über
      // die EIGENEN String-Schlüssel. Nicht-String-Quellen und nicht enthaltene
      // Schlüssel ergeben null (kein String()-Zwang, keine Prototype-Kette – sonst
      // liefen JS und Python auseinander, z. B. bei Zahlen/„toString").
      const derived = m != null
        ? (typeof src === 'string' && Object.prototype.hasOwnProperty.call(m, src)
            ? (m[src] ?? null) : null)
        : src
      if (f.overridable) {
        if (isEmpty(out[f.key]) && !isEmpty(derived)) { out[f.key] = derived; changed = true }
      } else if (out[f.key] !== derived) {
        out[f.key] = derived
        changed = true
      }
    }
    if (!changed) break
  }
  return out
}
