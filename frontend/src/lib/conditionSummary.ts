/**
 * Einzeilige deutsche Klartext-Zusammenfassung eines Condition-DSL-Ausdrucks.
 *
 * Warum eigenes Modul und nicht in der SFC: Die Regeln sind reine Logik mit
 * vielen Sonderfällen (Teil-Eingaben aus dem Editor, verschachtelte Gruppen) –
 * so sind sie ohne @vue/test-utils testbar (das Projekt hat keine
 * Komponenten-Tests).
 *
 * Bewusst TOLERANT: Der Editor liefert auch unfertige Ausdrücke (kein Feld
 * gewählt, leere UND-Gruppe). Die harte Prüfung macht
 * processValidate.isWellFormedCondition – hier wird nur beschrieben.
 */
import type { Condition } from '@/types/process'

/** Fehlende Bedingung = keine Einschränkung. */
export const CONDITION_ALWAYS = 'immer'
/** Struktur passt zu keinem DSL-Operator. */
export const CONDITION_INVALID = 'ungültige Bedingung'

const NO_FIELD = '(kein Feld)'

const OP_TEXT: Record<string, string> = {
  '==': 'ist gleich',
  '!=': 'ist ungleich',
  in: 'ist eine von',
}

/**
 * Wert-Darstellung. Strings kommen in Anführungszeichen, damit „Ja" (Text) und
 * Ja (Boolean) unterscheidbar bleiben – das Backend vergleicht strikt.
 */
export function formatConditionValue(v: unknown): string {
  if (v === null || v === undefined) return 'leer'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return `"${v}"`
  try {
    return JSON.stringify(v) ?? String(v)
  } catch {
    return String(v)
  }
}

export function summarizeCondition(
  cond: Condition | null | undefined,
  labels?: Record<string, string>,
): string {
  if (cond === null || cond === undefined) return CONDITION_ALWAYS
  if (typeof cond !== 'object' || Array.isArray(cond)) return CONDITION_INVALID

  const keys = Object.keys(cond)
  // Genau EIN Operator-Key pro Knoten – alles andere ist kein DSL-Ausdruck.
  if (keys.length !== 1) return CONDITION_INVALID

  const op = keys[0]
  const arg = (cond as Record<string, unknown>)[op]
  const lbl = (k: unknown): string => {
    if (typeof k !== 'string' || k === '') return NO_FIELD
    return labels?.[k] ?? k
  }

  switch (op) {
    case '==':
    case '!=': {
      if (!Array.isArray(arg) || arg.length < 2) return CONDITION_INVALID
      return `${lbl(arg[0])} ${OP_TEXT[op]} ${formatConditionValue(arg[1])}`
    }
    case 'in': {
      if (!Array.isArray(arg) || !Array.isArray(arg[1])) return CONDITION_INVALID
      const vals = arg[1].map(formatConditionValue).join(', ')
      return `${lbl(arg[0])} ${OP_TEXT.in} ${vals || '(leere Liste)'}`
    }
    case 'truthy':
      return `${lbl(arg)} ist gesetzt`
    case 'and':
    case 'or': {
      if (!Array.isArray(arg)) return CONDITION_INVALID
      if (arg.length === 0) return '(leer)'
      const join = op === 'and' ? ' UND ' : ' ODER '
      return `(${arg.map((c) => summarizeCondition(c as Condition, labels)).join(join)})`
    }
    case 'not': {
      if (arg === null || arg === undefined) return CONDITION_INVALID
      return `NICHT ${summarizeCondition(arg as Condition, labels)}`
    }
    default:
      return CONDITION_INVALID
  }
}
