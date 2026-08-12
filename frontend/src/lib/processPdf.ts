/**
 * Druckbare Zusammenfassung eines Prozess-Auftrags (PhaseView 'export').
 *
 * Prozessunabhängig: Kopf, Fuß, Abschnitte, Breiten und Reihenfolge kommen
 * ausschließlich aus der DEFINITION (über resolveLayout) und aus den übergebenen
 * Werten. Kein Wissen über einzelne Prozesse, keine hartcodierte Feldliste.
 *
 * Dreiteilung, damit die Zeichenlogik OHNE DOM prüfbar bleibt:
 *   1. buildExportDoc()   – Definition + Werte → reines Datenmodell (kein jsPDF).
 *   2. drawExportDoc()    – Datenmodell → Zeichenaufrufe auf einem PdfLike.
 *   3. exportProcessPdf() – lädt jspdf NACH, zeichnet, speichert.
 */
import type {
  FieldDef, LayoutItem, NoteTone, OptionSources, PhaseDef, ProcessDefinition, SectionVariant,
} from '@/types/process'
import { resolveLayout, REST_SECTION_TITLE } from '@/lib/processLayout'
import type { SimViewer } from '@/lib/processSim'
import {
  collectionEntries, EMPTY_TEXT, fieldLabel, fieldValueText, isEmptyValue, isWideWidget,
  subFieldLabel, subValueText,
} from '@/lib/processFieldFormat'

// ── Zeichen-Bereinigung (WinAnsi) ────────────────────────────────────────────

/**
 * Die jsPDF-Standardschriften (Helvetica & Co.) sind WinAnsi-kodiert. Alles
 * außerhalb von ASCII/Latin-1 lässt sich damit NICHT setzen – aufs Papier käme
 * ein falsches Zeichen oder ein leerer Kasten. Statt kaputt zu drucken wird
 * ersetzt:
 *   - typografische Zeichen (Gedankenstrich, „Anführungszeichen", …) → ASCII;
 *   - unsichtbare Steuerzeichen (Emoji-Verbinder, Variantenselektoren) → weg;
 *   - alles Übrige (Emoji, kyrillisch, CJK …) → '?', und das PDF weist im Fuß
 *     darauf hin, dass Zeichen ersetzt wurden (Ehrlichkeits-Regel).
 *
 * Der cp1252-Bereich 0x80–0x9F (€, ‚, †, …) wird bewusst NICHT genutzt: genau
 * dort weichen die Kodierungen voneinander ab. Das Euro-Zeichen wird zu 'EUR'.
 */
const CHAR_MAP: Record<string, string> = {
  ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', '\t': '  ',
  '­': '',
  '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-',
  '―': '-', '−': '-', '•': '-',
  '‘': "'", '’': "'", '‚': "'", '′': "'",
  '‹': '<', '›': '>',
  '“': '"', '”': '"', '„': '"', '″': '"',
  '…': '...', '→': '->', '←': '<-', '⇒': '=>',
  '≤': '<=', '≥': '>=', '≠': '!=', '≈': '~',
  '€': 'EUR', '™': '(TM)',
  'Š': 'S', 'š': 's', 'Ž': 'Z', 'ž': 'z',
  'Œ': 'OE', 'œ': 'oe', 'Ÿ': 'Y', 'ƒ': 'f',
  '⁄': '/',
}

/** Zeichen ohne eigene Fläche – ersatzlos streichen, kein Hinweis nötig. */
const INVISIBLE = /[​-‍⁠﻿︀-️]/g

export interface SanitizeResult { text: string; replaced: boolean }

export function toWinAnsi(input: string): SanitizeResult {
  let replaced = false
  let out = ''
  const src = input.replace(/\r\n?/g, '\n').replace(INVISIBLE, '')
  // Über Codepoints laufen: Emoji sind Surrogatpaare und dürfen nicht in zwei
  // einzelne '?' zerfallen.
  for (const ch of src) {
    const mapped = CHAR_MAP[ch]
    if (mapped !== undefined) { out += mapped; continue }
    const cp = ch.codePointAt(0) ?? 0
    if (ch === '\n' || (cp >= 0x20 && cp <= 0x7e) || (cp >= 0xa0 && cp <= 0xff)) {
      out += ch
      continue
    }
    out += '?'
    replaced = true
  }
  return { text: out, replaced }
}

/** Sammelt beim Aufbauen des Dokuments, ob irgendwo ersetzt werden musste. */
function sanitizer() {
  let replaced = false
  const fn = (s: string | null | undefined): string => {
    const r = toWinAnsi(String(s ?? ''))
    if (r.replaced) replaced = true
    return r.text
  }
  return { fn, wasReplaced: () => replaced }
}

// ── Datenmodell des Ausdrucks ────────────────────────────────────────────────

export interface ExportSubValue { label: string; value: string }

export type ExportBlock =
  | { kind: 'field'; cols: number; label: string; value: string; empty: boolean }
  | { kind: 'collection'; cols: number; label: string; entries: ExportSubValue[][] }
  /** `unknown: true` = dem Ausdruck wurden gar keine Dateinamen übergeben. */
  | { kind: 'attachment'; cols: number; label: string; files: string[]; unknown: boolean }
  | { kind: 'note'; cols: number; text: string; tone: NoteTone }
  | { kind: 'heading'; cols: number; text: string }
  | { kind: 'divider'; cols: number }
  | { kind: 'spacer'; cols: number }

export interface ExportSection {
  title: string
  variant: SectionVariant
  badge: string | null
  description: string | null
  blocks: ExportBlock[]
}

export interface ExportMeta {
  /** definition.name – die Überschrift des Ausdrucks. */
  processName: string
  ticketTitle: string
  /** z. B. '#128'; null, solange der Auftrag keine Nummer hat. */
  ticketNumber: string | null
  ownerName: string | null
  /** ISO-Zeitstempel der Anlage. */
  createdAt: string | null
  phaseLabel: string | null
}

export interface ExportDoc {
  meta: ExportMeta
  sections: ExportSection[]
  /** Grau gesetzte Sätze am Ende des Fließtextes. */
  footnotes: string[]
  /** true = mindestens ein Zeichen war nicht darstellbar und wurde ersetzt. */
  charsReplaced: boolean
}

export interface ExportInput {
  definition: ProcessDefinition
  /** Die Export-Phase; ohne Phase bleiben nur die erfassten Werte übrig. */
  phase: PhaseDef | null
  /** Vom Server bereits nach Sichtbarkeit GEFILTERTE Werte. */
  values: Record<string, unknown>
  viewer: SimViewer
  sources?: OptionSources
  meta: ExportMeta
  /** Dateinamen je Anhang-Feld. Fehlt die Angabe ganz, sagt das PDF das ehrlich. */
  attachments?: Record<string, string[]>
}

/** Was einen Abschnitt trägt – Trennlinie und Abstand allein sind visueller Müll. */
const SUBSTANTIAL: ReadonlySet<string> = new Set(
  ['field', 'collection', 'attachment', 'note', 'heading'])

const VISIBILITY_NOTE = 'Diese Ausgabe enthält nur die Werte, die der Server für die '
  + 'exportierende Person freigegeben hat. Als „Nicht angegeben" gekennzeichnete Felder '
  + 'können daher auch ausgeblendet sein.'

const CHARSET_NOTE = 'Einzelne Sonderzeichen (etwa Symbole oder Emoji) lassen sich in der '
  + 'PDF-Schrift nicht darstellen und wurden durch „?" ersetzt.'

export function buildExportDoc(input: ExportInput): ExportDoc {
  const { definition, phase, values, viewer, sources, attachments, meta } = input
  const s = sanitizer()
  const byKey = new Map(definition.fields.map((f) => [f.key, f]))

  /**
   * WERTE-GATE. Der Server hat `values` bereits gefiltert; das PDF trägt Werte
   * aber aus dem System heraus, deshalb wird hier NICHT dem `viewer` geglaubt
   * (die Detailansicht übergibt heute fullView=true). Gedruckt wird nur, was
   * wirklich in `values` steht – fehlt der Schlüssel, erscheint das Feld als
   * „Nicht angegeben", gleich ob leer oder ausgeblendet.
   */
  const has = (key: string) => Object.prototype.hasOwnProperty.call(values, key)

  const fieldBlock = (f: FieldDef, cols: number): ExportBlock => {
    // Dieselbe Verbreiterung wie in der Lese-Ansicht: was in einer schmalen
    // Spalte unlesbar wäre, bekommt die volle Zeile.
    const width = isWideWidget(f.widget) ? 12 : cols
    const label = s.fn(fieldLabel(f))
    const raw = has(f.key) ? values[f.key] : undefined

    if (f.widget === 'collection') {
      // Wiederholgruppen haben im PDF keine Tabellenform (jspdf-autotable ist
      // nicht installiert) – daher eingerückte Blöcke, einer je Eintrag.
      const entries = collectionEntries(raw).map((entry) =>
        (f.item ?? []).map((sf) => ({
          label: s.fn(subFieldLabel(sf)),
          value: s.fn(subValueText(entry[sf.key])),
        })))
      return { kind: 'collection', cols: width, label, entries }
    }

    if (f.widget === 'attachment') {
      // Anhänge liegen NICHT in den Werten, sondern in der Datei-Ablage des
      // Auftrags. Ohne übergebene Namen sagt das PDF das, statt das Feld
      // stillschweigend wegzulassen.
      const known = attachments !== undefined
      const files = (attachments?.[f.key] ?? []).map((n) => s.fn(n))
      return { kind: 'attachment', cols: width, label, files, unknown: !known }
    }

    const empty = !has(f.key) || isEmptyValue(raw)
    return {
      kind: 'field', cols: width, label,
      value: empty ? '' : s.fn(fieldValueText(f, raw, sources)),
      empty,
    }
  }

  const decoBlock = (item: LayoutItem, cols: number): ExportBlock => {
    if (item.type === 'note') return { kind: 'note', cols, text: s.fn(item.text), tone: item.tone }
    if (item.type === 'heading') return { kind: 'heading', cols, text: s.fn(item.text) }
    if (item.type === 'divider') return { kind: 'divider', cols }
    return { kind: 'spacer', cols }
  }

  // ── Abschnitte aus dem Phasen-Layout ───────────────────────────────────────
  const sections: ExportSection[] = []
  const shown = new Set<string>()

  for (const { section, items } of (phase ? resolveLayout(definition, phase, values, viewer) : [])) {
    const blocks: ExportBlock[] = []
    for (const it of items) {
      if (it.rendered) {
        const f = byKey.get(it.rendered.field.key)
        if (!f || shown.has(f.key)) continue
        shown.add(f.key)
        blocks.push(fieldBlock(f, it.cols))
      } else {
        blocks.push(decoBlock(it.item, it.cols))
      }
    }
    if (!blocks.some((b) => SUBSTANTIAL.has(b.kind))) continue
    sections.push({
      title: s.fn(section.title || 'Angaben'),
      variant: section.variant,
      badge: section.badge ? s.fn(section.badge) : null,
      description: section.description ? s.fn(section.description) : null,
      blocks,
    })
  }

  /**
   * Erfasste Werte, die in dieser Phase nicht vorkommen. Der Bildschirm sammelt
   * sie ebenfalls unter „Weitere Angaben"; im Ausdruck bleiben allerdings die
   * NICHT ausgefüllten Katalogfelder weg – ein Auftragsblatt voller „Nicht
   * angegeben" hilft der weiterverarbeitenden Stelle nicht.
   */
  const rest = definition.fields.filter((f) =>
    !shown.has(f.key) && has(f.key) && !isEmptyValue(values[f.key]))
  if (rest.length) {
    const restBlocks = rest.map((f) => fieldBlock(f, 6))
    const last = sections[sections.length - 1]
    if (last && last.title === REST_SECTION_TITLE) {
      // resolveLayout hat schon einen Sammel-Abschnitt angelegt – nicht zwei
      // gleichnamige untereinander setzen.
      last.blocks = [...last.blocks, ...restBlocks]
    } else {
      sections.push({
        title: sections.length ? REST_SECTION_TITLE : 'Angaben',
        variant: sections.length ? 'default' : 'base',
        badge: null, description: null, blocks: restBlocks,
      })
    }
  }

  const outMeta: ExportMeta = {
    processName: s.fn(meta.processName),
    ticketTitle: s.fn(meta.ticketTitle),
    ticketNumber: meta.ticketNumber ? s.fn(meta.ticketNumber) : null,
    ownerName: meta.ownerName ? s.fn(meta.ownerName) : null,
    createdAt: meta.createdAt,
    phaseLabel: meta.phaseLabel ? s.fn(meta.phaseLabel) : null,
  }

  // Erst JETZT abfragen: die Fußnoten selbst dürfen das Flag nicht setzen.
  const charsReplaced = s.wasReplaced()
  const footnotes = [toWinAnsi(VISIBILITY_NOTE).text]
  if (charsReplaced) footnotes.push(toWinAnsi(CHARSET_NOTE).text)

  return { meta: outMeta, sections, footnotes, charsReplaced }
}

// ── Zeichen-Schnittstelle (die von jsPDF genutzte Teilmenge) ─────────────────

export type RGB = readonly [number, number, number]
export type FontStyle = 'normal' | 'bold' | 'italic' | 'bolditalic'

/**
 * Nur das, was hier wirklich gebraucht wird – so lässt sich im Test eine
 * Attrappe einsetzen, die die Aufrufe mitschreibt (jsPDF selbst braucht ein DOM).
 */
export interface PdfLike {
  internal: { pageSize: { getWidth(): number; getHeight(): number } }
  setFontSize(size: number): unknown
  setFont(family: string, style: FontStyle): unknown
  setTextColor(r: number, g: number, b: number): unknown
  setFillColor(r: number, g: number, b: number): unknown
  setDrawColor(r: number, g: number, b: number): unknown
  setLineWidth(w: number): unknown
  rect(x: number, y: number, w: number, h: number, style?: string): unknown
  line(x1: number, y1: number, x2: number, y2: number): unknown
  text(text: string | string[], x: number, y: number, options?: { align?: string }): unknown
  splitTextToSize(text: string, width: number): string[]
  addPage(): unknown
  setPage(n: number): unknown
  getNumberOfPages(): number
}

// ── Farben & Maße ────────────────────────────────────────────────────────────

/**
 * Akzentfarbe je Abschnitts-Variante. Das Emoji-Icon aus VARIANT_STYLE wird
 * bewusst NICHT übernommen – WinAnsi kann es nicht zeichnen. Übrig bleibt der
 * Farbbalken, der die Varianten auch im Ausdruck unterscheidbar macht.
 */
const VARIANT_RGB: Record<SectionVariant, RGB> = {
  base: [62, 172, 182],
  hr: [59, 130, 246],
  it: [168, 85, 247],
  fuhrpark: [245, 158, 11],
  marketing: [236, 72, 153],
  travel: [20, 184, 166],
  default: [148, 163, 184],
}

/** Statt des Tonsymbols (Info/Warnung/Erledigt) steht im PDF sein Wort. */
const NOTE_RGB: Record<NoteTone, { label: string; bg: RGB; fg: RGB; bar: RGB }> = {
  info: { label: 'Hinweis', bg: [239, 246, 255], fg: [30, 64, 175], bar: [59, 130, 246] },
  warning: { label: 'Achtung', bg: [255, 251, 235], fg: [146, 64, 14], bar: [245, 158, 11] },
  success: { label: 'Erledigt', bg: [240, 253, 244], fg: [22, 101, 52], bar: [34, 197, 94] },
  neutral: { label: 'Notiz', bg: [249, 250, 251], fg: [55, 65, 81], bar: [156, 163, 175] },
}

const BRAND: RGB = [62, 170, 184]
const INK: RGB = [35, 35, 35]
const LABEL_GREY: RGB = [150, 150, 150]
const EMPTY_GREY: RGB = [175, 175, 175]
const RULE_GREY: RGB = [225, 225, 225]
const WHITE: RGB = [255, 255, 255]

const M = 16              // Seitenrand
const GUTTER = 6          // Abstand zwischen zwei Spalten
const HEADER_H = 30       // Farbbalken der ersten Seite
const TOP_FIRST = 42      // erste Textzeile auf Seite 1
const TOP_NEXT = 24       // erste Textzeile auf Folgeseiten
const BOTTOM = 18         // Freiraum für die Fußzeile

const LH_LABEL = 4.4
const LH_VALUE = 4.7
const LH_SMALL = 4.2
const GAP_FIELD = 4

// ── Zeichen-Grundelemente ────────────────────────────────────────────────────

/**
 * Eine gezeichnete Zeile. ALLES wird auf Zeilen heruntergebrochen, damit ein
 * Seitenumbruch überall sauber möglich ist: die Ausgabe schiebt Zeile für Zeile
 * und schaltet um, sobald die nächste nicht mehr passt.
 */
interface Line {
  /** Einrückung gegenüber dem linken Rand der Spalte. */
  dx: number
  /** Vertikaler Verbrauch (mm). */
  h: number
  size: number
  style: FontStyle
  color: RGB
  text?: string
  /** Hintergrund über die volle Spaltenbreite (Hinweisbox). */
  fill?: RGB
  /** Schmale Leiste am linken Rand (Hinweisbox, Wiederholgruppe). */
  bar?: RGB
  /** Waagerechte Linie statt Text (Trennlinie, Überschrift). */
  rule?: RGB
}

interface Prepared {
  cols: number
  width: number
  lines: Line[]
  height: number
  /** Nach einem Seitenumbruch wiederholte Beschriftung („… (FORTSETZUNG)"). */
  cont?: Line
}

function blank(h: number, extra: Partial<Line> = {}): Line {
  return { dx: 0, h, size: 0, style: 'normal', color: INK, ...extra }
}

/** Umbruch über jsPDF – die Breite hängt von Schriftgrad und -schnitt ab. */
function wrap(pdf: PdfLike, text: string, width: number, size: number, style: FontStyle): string[] {
  pdf.setFontSize(size)
  pdf.setFont('helvetica', style)
  const out = pdf.splitTextToSize(text, Math.max(width, 8))
  return out.length ? out : ['']
}

/**
 * Eine Zeile, hart auf die Breite gestutzt. Prozess- und Auftragsnamen kommen
 * aus der Pflege und können beliebig lang sein; jsPDF beschneidet nichts von
 * selbst, ein langer Titel liefe sonst in die rechte Kopfspalte hinein.
 */
function clip(pdf: PdfLike, text: string, width: number, size: number, style: FontStyle): string {
  const lines = wrap(pdf, text, width, size, style)
  return lines.length > 1 ? `${lines[0]}...` : (lines[0] ?? '')
}

function labelLines(pdf: PdfLike, label: string, width: number): Line[] {
  if (!label) return []
  return wrap(pdf, label.toUpperCase(), width, 7.5, 'bold').map((t): Line => ({
    dx: 0, h: LH_LABEL, size: 7.5, style: 'bold', color: LABEL_GREY, text: t,
  }))
}

function prepareField(pdf: PdfLike, b: Extract<ExportBlock, { kind: 'field' }>,
                      width: number): Line[] {
  const lines = labelLines(pdf, b.label, width)
  if (b.empty) {
    lines.push({ dx: 0, h: LH_VALUE, size: 9.5, style: 'italic', color: EMPTY_GREY,
      text: 'Nicht angegeben' })
  } else {
    for (const t of wrap(pdf, b.value, width, 10, 'normal')) {
      lines.push({ dx: 0, h: LH_VALUE, size: 10, style: 'normal', color: INK, text: t })
    }
  }
  lines.push(blank(GAP_FIELD))
  return lines
}

function prepareCollection(pdf: PdfLike, b: Extract<ExportBlock, { kind: 'collection' }>,
                           width: number): Line[] {
  const lines = labelLines(pdf, b.label, width)
  if (!b.entries.length) {
    lines.push({ dx: 0, h: LH_VALUE, size: 9.5, style: 'italic', color: EMPTY_GREY,
      text: 'Keine Einträge' })
    lines.push(blank(GAP_FIELD))
    return lines
  }
  const inner = width - 6
  b.entries.forEach((entry, i) => {
    lines.push(blank(1.5, { bar: RULE_GREY }))
    lines.push({ dx: 4, h: LH_LABEL, size: 7.5, style: 'bold', color: LABEL_GREY,
      text: `EINTRAG ${i + 1}`, bar: RULE_GREY })
    if (!entry.length) {
      lines.push({ dx: 4, h: LH_SMALL, size: 9, style: 'italic', color: EMPTY_GREY,
        text: 'Keine Unterfelder hinterlegt', bar: RULE_GREY })
    }
    for (const sub of entry) {
      for (const t of wrap(pdf, `${sub.label}: ${sub.value}`, inner, 9.5, 'normal')) {
        lines.push({ dx: 4, h: LH_SMALL, size: 9.5, style: 'normal', color: INK, text: t,
          bar: RULE_GREY })
      }
    }
    lines.push(blank(2, { bar: RULE_GREY }))
    if (i < b.entries.length - 1) lines.push(blank(1.5))
  })
  lines.push(blank(GAP_FIELD))
  return lines
}

function prepareAttachment(pdf: PdfLike, b: Extract<ExportBlock, { kind: 'attachment' }>,
                           width: number): Line[] {
  const lines = labelLines(pdf, b.label, width)
  if (b.unknown) {
    for (const t of wrap(pdf,
      'Dateien dieses Feldes liegen am Auftrag und sind nicht Teil dieses Ausdrucks.',
      width, 9.5, 'italic')) {
      lines.push({ dx: 0, h: LH_SMALL, size: 9.5, style: 'italic', color: EMPTY_GREY, text: t })
    }
  } else if (!b.files.length) {
    lines.push({ dx: 0, h: LH_VALUE, size: 9.5, style: 'italic', color: EMPTY_GREY,
      text: 'Keine Dateien hinterlegt' })
  } else {
    for (const name of b.files) {
      // Dateinamen brechen selten sinnvoll – Folgezeilen einrücken, damit die
      // Aufzählung als Aufzählung lesbar bleibt.
      wrap(pdf, `- ${name}`, width - 4, 9.5, 'normal').forEach((t, i) => lines.push({
        dx: i === 0 ? 0 : 3, h: LH_SMALL, size: 9.5, style: 'normal', color: INK, text: t,
      }))
    }
  }
  lines.push(blank(GAP_FIELD))
  return lines
}

function prepareNote(pdf: PdfLike, b: Extract<ExportBlock, { kind: 'note' }>,
                     width: number): Line[] {
  const tone = NOTE_RGB[b.tone] ?? NOTE_RGB.neutral
  const lines: Line[] = [blank(2, { fill: tone.bg, bar: tone.bar })]
  lines.push({ dx: 4, h: LH_SMALL, size: 8, style: 'bold', color: tone.fg,
    text: tone.label.toUpperCase(), fill: tone.bg, bar: tone.bar })
  for (const t of wrap(pdf, b.text, width - 8, 9.5, 'normal')) {
    lines.push({ dx: 4, h: LH_SMALL, size: 9.5, style: 'normal', color: tone.fg, text: t,
      fill: tone.bg, bar: tone.bar })
  }
  lines.push(blank(2.5, { fill: tone.bg, bar: tone.bar }))
  lines.push(blank(GAP_FIELD))
  return lines
}

function prepareBlock(pdf: PdfLike, b: ExportBlock, width: number): Line[] {
  switch (b.kind) {
    case 'field': return prepareField(pdf, b, width)
    case 'collection': return prepareCollection(pdf, b, width)
    case 'attachment': return prepareAttachment(pdf, b, width)
    case 'note': return prepareNote(pdf, b, width)
    case 'heading': return [
      ...wrap(pdf, b.text.toUpperCase(), width, 8, 'bold').map((t): Line => ({
        dx: 0, h: 4.6, size: 8, style: 'bold', color: LABEL_GREY, text: t })),
      blank(1.6, { rule: RULE_GREY }),
      blank(2.4),
    ]
    case 'divider': return [blank(3), blank(1.4, { rule: RULE_GREY }), blank(2)]
    default: return [blank(6)]
  }
}

function blockLabel(b: ExportBlock): string {
  return b.kind === 'field' || b.kind === 'collection' || b.kind === 'attachment' ? b.label : ''
}

// ── Ausgabe ──────────────────────────────────────────────────────────────────

/** Zeitstempel ohne Intl/Zeitzone – der Ausdruck muss überall gleich aussehen. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return EMPTY_TEXT
  const dt = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso)
  if (dt) return `${dt[3]}.${dt[2]}.${dt[1]} ${dt[4]}:${dt[5]} Uhr`
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (d) return `${d[3]}.${d[2]}.${d[1]}`
  return iso
}

export function drawExportDoc(pdf: PdfLike, doc: ExportDoc): void {
  const pageW = pdf.internal.pageSize.getWidth()
  const pageH = pdf.internal.pageSize.getHeight()
  const right = pageW - M
  const content = pageW - 2 * M
  const bottom = pageH - BOTTOM
  let y = 0

  const setFill = (c: RGB) => pdf.setFillColor(c[0], c[1], c[2])
  const setText = (c: RGB) => pdf.setTextColor(c[0], c[1], c[2])
  const setDraw = (c: RGB) => pdf.setDrawColor(c[0], c[1], c[2])
  /** Letztes Netz für Texte, die erst hier zusammengesetzt werden (Kopf/Fuß). */
  const ansi = (t: string) => toWinAnsi(t).text

  // ── Kopf ───────────────────────────────────────────────────────────────────
  function drawFirstHeader() {
    // Links Titel, rechts die Kopfdaten – beide Spalten gestutzt, damit sie sich
    // bei langen Namen nicht überschreiben.
    const titleW = content - 58
    const title = clip(pdf, doc.meta.processName || 'Auftrag', titleW, 19, 'bold')
    const sub = clip(pdf, doc.meta.ticketTitle || '', titleW, 11, 'normal')
    setFill(BRAND)
    pdf.rect(0, 0, pageW, HEADER_H, 'F')
    setText(WHITE)
    pdf.setFontSize(19); pdf.setFont('helvetica', 'bold')
    pdf.text(title, M, 14)
    pdf.setFontSize(11); pdf.setFont('helvetica', 'normal')
    pdf.text(sub, M, 22)
    pdf.setFontSize(8.5)
    const rows = [
      doc.meta.ticketNumber ? `Auftrag ${doc.meta.ticketNumber}` : null,
      `Erstellt von: ${doc.meta.ownerName || '-'}`,
      `Angelegt: ${formatTimestamp(doc.meta.createdAt)}`,
      doc.meta.phaseLabel ? `Phase: ${doc.meta.phaseLabel}` : null,
    ].filter((r): r is string => !!r)
    rows.forEach((t, i) => pdf.text(ansi(t), right, 8.5 + i * 5.2, { align: 'right' }))
    y = TOP_FIRST
  }

  /** Folgeseiten tragen eine schmale Kopfzeile, damit lose Blätter zuordenbar sind. */
  function newPage() {
    pdf.addPage()
    pdf.setFontSize(8); pdf.setFont('helvetica', 'normal')
    setText(LABEL_GREY)
    const caption = ansi([doc.meta.processName, doc.meta.ticketNumber].filter(Boolean).join(' - '))
    pdf.text(clip(pdf, caption, content, 8, 'normal'), M, 13)
    setDraw(RULE_GREY); pdf.setLineWidth(0.2)
    pdf.line(M, 16, right, 16)
    y = TOP_NEXT
  }

  const ensure = (h: number) => { if (y + h > bottom) newPage() }

  function drawLine(l: Line, x: number, top: number, w: number) {
    if (l.fill) { setFill(l.fill); pdf.rect(x, top, w, l.h, 'F') }
    if (l.bar) { setFill(l.bar); pdf.rect(x, top, 1.5, l.h, 'F') }
    if (l.rule) {
      setDraw(l.rule); pdf.setLineWidth(0.2)
      pdf.line(x, top + l.h / 2, x + w, top + l.h / 2)
    }
    if (l.text) {
      pdf.setFontSize(l.size)
      pdf.setFont('helvetica', l.style)
      setText(l.color)
      // `top` ist die Oberkante der Zeile; jsPDF setzt Text auf die Grundlinie.
      pdf.text(l.text, x + l.dx, top + l.h - 1.2)
    }
  }

  function drawSectionHeader(sec: ExportSection) {
    // Kopf und erste Zeile zusammenhalten, sonst steht die Überschrift allein
    // am Seitenfuß.
    ensure(24)
    y += 5
    const accent = VARIANT_RGB[sec.variant] ?? VARIANT_RGB.default
    const title = clip(pdf, sec.title, content - (sec.badge ? 46 : 8), 11.5, 'bold')
    const badge = sec.badge ? clip(pdf, sec.badge, 40, 8, 'normal') : null
    setFill(accent)
    pdf.rect(M, y - 3.4, 2.6, 5, 'F')
    pdf.setFontSize(11.5); pdf.setFont('helvetica', 'bold')
    setText(accent)
    pdf.text(title, M + 5.5, y)
    if (badge) {
      pdf.setFontSize(8); pdf.setFont('helvetica', 'normal')
      pdf.text(badge, right, y, { align: 'right' })
    }
    y += 6.5
    if (sec.description) {
      const lines = wrap(pdf, sec.description, content, 8.5, 'italic')
      setText(LABEL_GREY)
      lines.forEach((t, i) => pdf.text(t, M, y + i * 4.2))
      y += lines.length * 4.2 + 1.5
    }
  }

  /**
   * Volle Breite: Zeile für Zeile mit Umbruchprüfung. Reißt die Seite mitten im
   * Block, wird die Beschriftung als „(FORTSETZUNG)" wiederholt.
   */
  function drawFlowing(p: Prepared) {
    let emitted = 0
    for (const l of p.lines) {
      if (y + l.h > bottom) {
        newPage()
        // Nur wiederholen, wenn oben schon etwas von diesem Block stand –
        // sonst stünde die Beschriftung zweimal hintereinander.
        if (p.cont && emitted > 0) { drawLine(p.cont, M, y, p.width); y += p.cont.h }
      }
      drawLine(l, M, y, p.width)
      y += l.h
      emitted += 1
    }
  }

  /** Zeilen des 12er-Rasters – dieselbe Reihenfolge und Breite wie am Bildschirm. */
  function toRows(prepared: Prepared[]): Prepared[][] {
    const rows: Prepared[][] = []
    let row: Prepared[] = []
    let used = 0
    for (const p of prepared) {
      if (used + p.cols > 12 && row.length) { rows.push(row); row = []; used = 0 }
      row.push(p)
      used += p.cols
    }
    if (row.length) rows.push(row)
    return rows
  }

  function prepareAll(blocks: ExportBlock[]): Prepared[] {
    const bodyH = bottom - TOP_NEXT
    return blocks.map((b) => {
      let cols = Math.min(12, Math.max(1, b.cols || 12))
      // Immer inklusive Rinne rechnen – so bleibt die Vorbereitung gültig,
      // egal ob der Block später als letzter in seiner Zeile steht.
      let width = (cols / 12) * content - GUTTER
      let lines = prepareBlock(pdf, b, width)
      let height = lines.reduce((a, l) => a + l.h, 0)
      if (cols < 12 && height > bodyH) {
        // Passt in seiner Spalte auf keine Seite – nur volle Breite lässt sich
        // über Seiten hinweg umbrechen.
        cols = 12
        width = content - GUTTER
        lines = prepareBlock(pdf, b, width)
        height = lines.reduce((a, l) => a + l.h, 0)
      }
      const label = blockLabel(b)
      const cont: Line | undefined = label
        ? { dx: 0, h: LH_LABEL, size: 7.5, style: 'bold', color: LABEL_GREY,
          text: `${label.toUpperCase()} (FORTSETZUNG)` }
        : undefined
      return { cols, width, lines, height, cont }
    })
  }

  drawFirstHeader()

  for (const sec of doc.sections) {
    drawSectionHeader(sec)
    for (const r of toRows(prepareAll(sec.blocks))) {
      if (r.length === 1 && r[0].cols === 12) { drawFlowing(r[0]); continue }
      const h = Math.max(...r.map((p) => p.height))
      ensure(h)
      let offset = 0
      for (const p of r) {
        const x = M + (offset / 12) * content
        let top = y
        for (const l of p.lines) { drawLine(l, x, top, p.width); top += l.h }
        offset += p.cols
      }
      y += h
    }
  }

  if (!doc.sections.length) {
    ensure(10)
    pdf.setFontSize(10); pdf.setFont('helvetica', 'italic')
    setText(EMPTY_GREY)
    pdf.text('Keine sichtbaren Angaben.', M, y)
    y += 8
  }

  // ── Fußnoten ───────────────────────────────────────────────────────────────
  for (const note of doc.footnotes) {
    const lines = wrap(pdf, note, content, 7.5, 'italic')
    ensure(lines.length * 3.6 + 3)
    // Schrift nach ensure() erneut setzen: es kann eine neue Seite begonnen haben.
    pdf.setFontSize(7.5); pdf.setFont('helvetica', 'italic')
    setText(LABEL_GREY)
    lines.forEach((t, i) => pdf.text(t, M, y + 3 + i * 3.6))
    y += lines.length * 3.6 + 3
  }

  // ── Fußzeile auf allen Seiten ──────────────────────────────────────────────
  const pages = pdf.getNumberOfPages()
  // Platz für „Seite i / n" rechts freilassen.
  const foot = clip(pdf, ansi([doc.meta.processName, doc.meta.ticketNumber, doc.meta.ownerName]
    .filter(Boolean).join(' - ')), content - 30, 7.5, 'normal')
  for (let i = 1; i <= pages; i++) {
    pdf.setPage(i)
    setDraw(RULE_GREY); pdf.setLineWidth(0.2)
    pdf.line(M, pageH - 14, right, pageH - 14)
    pdf.setFontSize(7.5); pdf.setFont('helvetica', 'normal')
    setText(LABEL_GREY)
    pdf.text(foot, M, pageH - 9)
    pdf.text(`Seite ${i} / ${pages}`, right, pageH - 9, { align: 'right' })
  }
}

// ── Dateiname & Einstieg ─────────────────────────────────────────────────────

const TRANSLIT: Record<string, string> = {
  'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss',
}

export function exportFileName(meta: ExportMeta): string {
  const raw = [meta.processName || 'Auftrag', meta.ticketNumber ?? ''].filter(Boolean).join('_')
  const safe = raw
    // `\w` kennt keine Umlaute – deshalb erst umschreiben, dann säubern.
    .replace(/[äöüÄÖÜß]/g, (c) => TRANSLIT[c] ?? c)
    .replace(/[^\w]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
  return `${safe || 'Auftrag'}.pdf`
}

/**
 * Erzeugt das PDF und stößt den Download an; gibt den Dateinamen zurück.
 *
 * jspdf wird hier NACHGELADEN: die Bibliothek wiegt rund 129 kB gzip und darf
 * nicht im Chunk jedes Prozess-Auftrags landen, sondern erst beim Klick auf
 * „PDF exportieren".
 */
export async function exportProcessPdf(input: ExportInput): Promise<string> {
  const { jsPDF } = await import('jspdf')
  const pdf = new jsPDF({ unit: 'mm', format: 'a4' })
  const doc = buildExportDoc(input)
  drawExportDoc(pdf as unknown as PdfLike, doc)
  const name = exportFileName(doc.meta)
  pdf.save(name)
  return name
}
