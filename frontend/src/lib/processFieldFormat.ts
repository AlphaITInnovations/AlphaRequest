/**
 * Wertdarstellung eines Prozess-Feldes – gemeinsam für Bildschirm und Ausdruck.
 *
 * Herausgezogen aus components/process/form/SchemaReadonlyView.vue: die
 * Export-/Druckansicht muss denselben Text zeigen wie die Lese-Ansicht. Läge die
 * Logik weiter in der .vue-Datei, gäbe es entweder eine Kopie (die
 * auseinanderläuft) oder einen DOM-Zwang im Test – das Projekt hat kein jsdom.
 *
 * Reines Modul: kein Vue, kein DOM, keine Uhrzeit-Zone.
 */
import type { FieldDef, OptionSources, SubField, Widget } from '@/types/process'

/** Platzhalter für „kein Wert" – identisch zur Lese-Ansicht. */
export const EMPTY_TEXT = '—'

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/
const ISO_DT = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/

/** ISO-Datum/-Zeit (aus `<input type="date"/"datetime-local">`) → deutsches
 *  Format: `2026-08-24` → `24.08.2026`. Alles andere bleibt unverändert. */
export function formatIsoDate(v: string): string {
  let m = ISO_DATE.exec(v)
  if (m) return `${m[3]}.${m[2]}.${m[1]}`
  m = ISO_DT.exec(v)
  if (m) return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`
  return v
}

/**
 * „Leer" heißt: es steht nichts drin, was man drucken könnte. `false` ist NICHT
 * leer (das ist die Antwort „Nein"), eine leere Liste dagegen schon.
 */
export function isEmptyValue(raw: unknown): boolean {
  if (raw === null || raw === undefined || raw === '') return true
  if (Array.isArray(raw)) return raw.length === 0
  return false
}

export function fieldLabel(f: FieldDef): string {
  return f.label || f.key
}

export function subFieldLabel(sf: SubField): string {
  return sf.label || sf.key
}

/** Volle Breite für alles, was in einer schmalen Spalte unlesbar würde. */
export function isWideWidget(w: Widget): boolean {
  return w === 'textarea' || w === 'collection' || w === 'attachment'
}

// ── Namen aus den Stammdaten ─────────────────────────────────────────────────

function userName(id: string, sources?: OptionSources): string {
  return sources?.users.find((u) => u.id === id)?.displayName || id
}

function groupName(id: string, sources?: OptionSources): string {
  return sources?.groups.find((g) => g.id === id)?.name || id
}

/** Einen einzelnen Wert über Optionen bzw. Stammdaten in einen Namen übersetzen. */
export function optionLabel(f: FieldDef, raw: unknown, sources?: OptionSources): string {
  const v = String(raw)
  if (f.widget === 'user' || f.optionsSource === 'users') return userName(v, sources)
  if (f.widget === 'group' || f.optionsSource === 'groups') return groupName(v, sources)
  const opt = (f.options ?? []).find((o) => o.value === v)
  return opt ? (opt.label ?? opt.value) : formatIsoDate(v)
}

/** Der anzeigbare Text eines Feldwertes – Ja/Nein, Options-Beschriftung, Namen. */
export function fieldValueText(f: FieldDef, raw: unknown, sources?: OptionSources): string {
  if (raw === null || raw === undefined || raw === '') return EMPTY_TEXT
  if (typeof raw === 'boolean') return raw ? 'Ja' : 'Nein'
  if (Array.isArray(raw)) {
    return raw.length ? raw.map((x) => optionLabel(f, x, sources)).join(', ') : EMPTY_TEXT
  }
  if (typeof raw === 'object') return JSON.stringify(raw)
  return optionLabel(f, raw, sources)
}

// ── Wiederholgruppen ─────────────────────────────────────────────────────────

/**
 * Unterfelder tragen keinen eigenen Options-Katalog (SubField hat keine
 * `options`), deshalb bleibt hier der rohe Wert stehen – genau wie am Bildschirm.
 */
export function subValueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return EMPTY_TEXT
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (Array.isArray(v)) {
    return v.length ? v.map((x) => formatIsoDate(String(x))).join(', ') : EMPTY_TEXT
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return formatIsoDate(String(v))
}

/** Alles, was keine Objekt-Zeile ist, wird zu {} – damit bleiben die Indizes stabil. */
export function collectionEntries(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) return []
  return raw.map((e) =>
    e && typeof e === 'object' && !Array.isArray(e) ? (e as Record<string, unknown>) : {})
}
