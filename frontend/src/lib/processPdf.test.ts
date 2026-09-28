/**
 * Tests der Export-/Druckansicht.
 *
 * Geprüft wird die reine Logik: aus Definition + Werten wird ein Datenmodell,
 * aus dem Datenmodell werden Zeichenaufrufe. jsPDF braucht ein DOM und wird
 * deshalb durch eine Attrappe ersetzt, die alle Aufrufe mitschreibt.
 */
import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import {
  buildExportDoc, drawExportDoc, exportFileName, formatTimestamp, toWinAnsi,
} from './processPdf'
import type { ExportBlock, ExportInput, ExportMeta, PdfLike } from './processPdf'
import type { SimViewer } from './processSim'
import type { OptionSources } from '@/types/process'

const VIEWER: SimViewer = { fullView: true, isAdmin: true, groupIds: [] }

const META: ExportMeta = {
  processName: 'Hotelbuchung',
  ticketTitle: 'Reise nach Köln',
  ticketNumber: '#128',
  ownerName: 'Marco Schneider',
  createdAt: '2026-08-10T09:05:00',
  phaseLabel: 'Reisestelle',
}

const SOURCES: OptionSources = {
  groups: [{ id: 'g-it', name: 'IT-Abteilung' }],
  users: [{ id: 'u-1', displayName: 'Anna Beispiel' }],
  companies: ['Alpha IT'],
}

// ── jsPDF-Attrappe ───────────────────────────────────────────────────────────

interface Call { fn: string; args: unknown[] }
interface TextCall { text: string; x: number; y: number; page: number }

/**
 * Zeichnet nichts, schreibt alles mit. `splitTextToSize` bricht grob nach einer
 * festen Zeichenbreite um – das reicht, um Umbrüche und Seitenwechsel
 * reproduzierbar auszulösen.
 */
function fakePdf(pageW = 210, pageH = 297) {
  const calls: Call[] = []
  let pages = 1
  let page = 1
  const CHAR_MM = 1.8

  const rec = (fn: string) => (...args: unknown[]): unknown => {
    calls.push({ fn, args })
    return undefined
  }

  const pdf: PdfLike = {
    internal: { pageSize: { getWidth: () => pageW, getHeight: () => pageH } },
    setFontSize: rec('setFontSize'),
    setFont: rec('setFont'),
    setTextColor: rec('setTextColor'),
    setFillColor: rec('setFillColor'),
    setDrawColor: rec('setDrawColor'),
    setLineWidth: rec('setLineWidth'),
    rect: rec('rect'),
    line: rec('line'),
    text: (text, x, y, options) => {
      calls.push({ fn: 'text', args: [text, x, y, options, page] })
      return undefined
    },
    splitTextToSize: (text, width) => {
      const perLine = Math.max(4, Math.floor(width / CHAR_MM))
      const out: string[] = []
      for (const para of String(text).split('\n')) {
        let line = ''
        for (const word of para.split(' ')) {
          const next = line ? `${line} ${word}` : word
          if (next.length > perLine && line) { out.push(line); line = word } else { line = next }
        }
        out.push(line)
      }
      return out
    },
    addPage: () => { pages += 1; page = pages; calls.push({ fn: 'addPage', args: [] }); return undefined },
    setPage: (n) => { page = n; calls.push({ fn: 'setPage', args: [n] }); return undefined },
    getNumberOfPages: () => pages,
  }

  const texts = (): TextCall[] => calls.filter((c) => c.fn === 'text').map((c) => ({
    text: String(c.args[0]), x: c.args[1] as number, y: c.args[2] as number,
    page: c.args[4] as number,
  }))

  return { pdf, calls, texts, pageCount: () => pages }
}

// ── Definitionen ─────────────────────────────────────────────────────────────

function demoDefinition(extra: Record<string, unknown> = {}) {
  return normalizeDefinition({
    key: 'hotel', name: 'Hotelbuchung',
    fields: [
      { key: 'name', widget: 'text', label: 'Name' },
      { key: 'ort', widget: 'text', label: 'Ort' },
      { key: 'anlass', widget: 'select', label: 'Anlass',
        options: [{ value: 'kunde', label: 'Kundentermin' }] },
      { key: 'fruehstueck', widget: 'checkbox', label: 'Frühstück' },
      { key: 'betreuer', widget: 'user', label: 'Betreuung' },
      { key: 'begruendung', widget: 'textarea', label: 'Begründung' },
      { key: 'naechte', widget: 'collection', label: 'Nächte',
        item: [{ key: 'datum', label: 'Datum', widget: 'date' },
          { key: 'preis', label: 'Preis', widget: 'number' }] },
      { key: 'belege', widget: 'attachment', label: 'Belege' },
      { key: 'intern', widget: 'text', label: 'Interne Notiz' },
    ],
    phases: [{
      key: 'export', label: 'Reisestelle', kind: 'task', view: 'export',
      fields: [
        { ref: 'name' }, { ref: 'ort' }, { ref: 'anlass' }, { ref: 'fruehstueck' },
        { ref: 'betreuer' }, { ref: 'begruendung' }, { ref: 'naechte' }, { ref: 'belege' },
      ],
      layout: [
        { type: 'section', title: 'Antragsteller', variant: 'hr', badge: 'Pflicht',
          description: 'Angaben zur reisenden Person',
          items: [
            { type: 'field', ref: 'name', width: 'quarter' },
            { type: 'field', ref: 'ort', width: 'third' },
            { type: 'field', ref: 'anlass', width: 'twothirds' },
          ] },
        { type: 'section', title: 'Details', variant: 'travel', items: [
          { type: 'heading', text: 'Zusatz' },
          { type: 'note', text: 'Bitte Budget beachten', tone: 'warning', width: 'full' },
          { type: 'field', ref: 'fruehstueck', width: 'half' },
          { type: 'field', ref: 'betreuer', width: 'half' },
          { type: 'divider' },
          { type: 'field', ref: 'begruendung', width: 'half' },
          { type: 'field', ref: 'naechte', width: 'half' },
          { type: 'field', ref: 'belege', width: 'half' },
        ] },
      ],
      ...extra,
    }],
  })
}

function build(values: Record<string, unknown>, over: Partial<ExportInput> = {}) {
  const definition = demoDefinition()
  return buildExportDoc({
    definition, phase: definition.phases[0], values, viewer: VIEWER,
    sources: SOURCES, meta: META, ...over,
  })
}

function blocksOf(doc: ReturnType<typeof build>, title: string): ExportBlock[] {
  return doc.sections.find((s) => s.title === title)?.blocks ?? []
}

// ── Zeichen-Bereinigung ──────────────────────────────────────────────────────

describe('toWinAnsi', () => {
  it('lässt Umlaute und ASCII unangetastet', () => {
    const r = toWinAnsi('Grüße aus Köln – 30 °C')
    expect(r.text).toBe('Grüße aus Köln - 30 °C')
    expect(r.replaced).toBe(false)
  })

  it('setzt typografische Zeichen auf ASCII um, ohne einen Verlust zu melden', () => {
    const r = toWinAnsi('„Test" – ‚eins‘ … ≤ 5 € ✓'.replace(' ✓', ''))
    expect(r.text).toBe('"Test" - \'eins\' ... <= 5 EUR')
    expect(r.replaced).toBe(false)
  })

  it('ersetzt Emoji durch ein einzelnes Fragezeichen und meldet den Verlust', () => {
    const r = toWinAnsi('Reise ✈️ nach 東京')
    // Das Surrogatpaar darf NICHT in zwei '?' zerfallen; der Variantenselektor
    // von ✈️ ist unsichtbar und verschwindet ersatzlos.
    expect(r.text).toBe('Reise ? nach ??')
    expect(r.replaced).toBe(true)
  })

  it('vereinheitlicht Zeilenenden und entfernt unsichtbare Steuerzeichen', () => {
    const r = toWinAnsi('a\r\nb​c')
    expect(r.text).toBe('a\nbc')
    expect(r.replaced).toBe(false)
  })
})

// ── Datenmodell ──────────────────────────────────────────────────────────────

describe('buildExportDoc – Abschnitte, Reihenfolge, Breiten', () => {
  const doc = build({
    name: 'Marco', ort: 'Köln', anlass: 'kunde', fruehstueck: true, betreuer: 'u-1',
  })

  it('übernimmt Titel und Reihenfolge aus dem Layout', () => {
    expect(doc.sections.map((s) => s.title)).toEqual(['Antragsteller', 'Details'])
    expect(doc.sections[0].variant).toBe('hr')
    expect(doc.sections[0].badge).toBe('Pflicht')
    expect(doc.sections[0].description).toBe('Angaben zur reisenden Person')
  })

  it('übernimmt die Spaltenbreiten aus resolveLayout', () => {
    expect(blocksOf(doc, 'Antragsteller').map((b) => b.cols)).toEqual([3, 4, 8])
  })

  it('setzt breite Widgets auf die volle Zeile – wie die Lese-Ansicht', () => {
    const details = blocksOf(doc, 'Details')
    const wide = details.filter((b) => ['collection', 'attachment'].includes(b.kind)
      || (b.kind === 'field' && b.label === 'BEGRÜNDUNG'))
    expect(wide.every((b) => b.cols === 12)).toBe(true)
    // Zum Vergleich: ein schmales Feld behält seine Layout-Breite.
    const check = details.find((b) => b.kind === 'field' && b.label === 'Frühstück')
    expect(check?.cols).toBe(6)
  })

  it('übernimmt die Deko-Elemente des Layouts', () => {
    expect(blocksOf(doc, 'Details').map((b) => b.kind).slice(0, 5))
      .toEqual(['heading', 'note', 'field', 'field', 'divider'])
  })
})

describe('buildExportDoc – Werte', () => {
  it('zeigt dieselben Texte wie die Lese-Ansicht (Ja/Nein, Option, Person)', () => {
    const doc = build({ anlass: 'kunde', fruehstueck: false, betreuer: 'u-1' })
    const byLabel = new Map(doc.sections.flatMap((s) => s.blocks)
      .filter((b) => b.kind === 'field')
      .map((b) => [b.label, b.value]))
    expect(byLabel.get('Anlass')).toBe('Kundentermin')
    expect(byLabel.get('Frühstück')).toBe('Nein')
    expect(byLabel.get('Betreuung')).toBe('Anna Beispiel')
  })

  it('markiert fehlende Werte als leer, statt sie wegzulassen', () => {
    const doc = build({ name: 'Marco' })
    const ort = blocksOf(doc, 'Antragsteller').find((b) => b.kind === 'field' && b.label === 'Ort')
    expect(ort).toMatchObject({ kind: 'field', empty: true, value: '' })
  })

  it('druckt keinen Wert, dessen Schlüssel gar nicht übergeben wurde', () => {
    // Der Server filtert vertrauliche Felder AUS `values` heraus. Das PDF darf
    // sie deshalb nicht aus der Definition rekonstruieren.
    const doc = build({})
    const values = doc.sections.flatMap((s) => s.blocks)
      .filter((b) => b.kind === 'field').map((b) => b.value)
    expect(values.every((v) => v === '')).toBe(true)
  })

  it('nimmt erfasste Werte außerhalb der Phase in einen Sammel-Abschnitt', () => {
    const doc = build({ name: 'Marco', intern: 'Nur intern' })
    const last = doc.sections[doc.sections.length - 1]
    expect(last.title).toBe('Weitere Angaben')
    expect(last.blocks).toEqual([
      { kind: 'field', cols: 6, label: 'Interne Notiz', value: 'Nur intern', empty: false },
    ])
  })

  it('führt keine leeren Katalogfelder im Sammel-Abschnitt auf', () => {
    const doc = build({ name: 'Marco', intern: '' })
    expect(doc.sections.map((s) => s.title)).toEqual(['Antragsteller', 'Details'])
  })
})

describe('buildExportDoc – Wiederholgruppen und Anhänge', () => {
  it('löst eine Wiederholgruppe in beschriftete Einträge auf', () => {
    const doc = build({ naechte: [{ datum: '2026-09-01', preis: 119 }, { datum: '2026-09-02' }] })
    const coll = blocksOf(doc, 'Details').find((b) => b.kind === 'collection')
    expect(coll).toEqual({
      kind: 'collection', cols: 12, label: 'Nächte',
      entries: [
        [{ label: 'Datum', value: '01.09.2026' }, { label: 'Preis', value: '119' }],
        // Der Gedankenstrich-Platzhalter der Lese-Ansicht ist in WinAnsi nicht
        // darstellbar und wird zum Bindestrich – ohne Verlustmeldung.
        [{ label: 'Datum', value: '02.09.2026' }, { label: 'Preis', value: '-' }],
      ],
    })
  })

  it('zeigt eine leere Wiederholgruppe als leere Liste, nicht als fehlendes Feld', () => {
    const doc = build({ naechte: [] })
    const coll = blocksOf(doc, 'Details').find((b) => b.kind === 'collection')
    expect(coll).toMatchObject({ kind: 'collection', entries: [] })
  })

  it('sagt bei Anhängen ehrlich, dass keine Dateinamen vorliegen', () => {
    const doc = build({})
    expect(blocksOf(doc, 'Details').find((b) => b.kind === 'attachment'))
      .toMatchObject({ unknown: true, files: [] })
  })

  it('listet übergebene Dateinamen auf', () => {
    const doc = build({}, { attachments: { belege: ['rechnung.pdf', 'bahn.pdf'] } })
    expect(blocksOf(doc, 'Details').find((b) => b.kind === 'attachment'))
      .toMatchObject({ unknown: false, files: ['rechnung.pdf', 'bahn.pdf'] })
  })

  it('unterscheidet „keine Dateien" von „keine Angabe"', () => {
    const doc = build({}, { attachments: {} })
    expect(blocksOf(doc, 'Details').find((b) => b.kind === 'attachment'))
      .toMatchObject({ unknown: false, files: [] })
  })
})

describe('buildExportDoc – Fußnoten', () => {
  it('weist immer auf die serverseitige Filterung hin', () => {
    expect(build({}).footnotes[0]).toContain('freigegeben')
    expect(build({}).charsReplaced).toBe(false)
  })

  it('ergänzt einen Hinweis, sobald Zeichen ersetzt werden mussten', () => {
    const doc = build({ name: 'Marco 🚀' })
    expect(doc.charsReplaced).toBe(true)
    expect(doc.footnotes).toHaveLength(2)
    expect(doc.footnotes[1]).toContain('Sonderzeichen')
    const name = blocksOf(doc, 'Antragsteller')
      .find((b) => b.kind === 'field' && b.label === 'Name')
    expect(name).toMatchObject({ value: 'Marco ?' })
  })

  it('bereinigt auch die Kopfdaten', () => {
    const doc = build({}, { meta: { ...META, ticketTitle: 'Reise 🚄 Köln' } })
    expect(doc.meta.ticketTitle).toBe('Reise ? Köln')
    expect(doc.charsReplaced).toBe(true)
  })
})

describe('buildExportDoc – ohne Phase', () => {
  it('liefert nur die erfassten Werte in einem Abschnitt „Angaben"', () => {
    const definition = demoDefinition()
    const doc = buildExportDoc({
      definition, phase: null, values: { name: 'Marco' }, viewer: VIEWER, meta: META,
    })
    expect(doc.sections.map((s) => s.title)).toEqual(['Angaben'])
    expect(doc.sections[0].variant).toBe('base')
    expect(doc.sections[0].blocks).toHaveLength(1)
  })
})

// ── Zeichenaufrufe ───────────────────────────────────────────────────────────

describe('drawExportDoc', () => {
  it('setzt Kopf, Abschnittstitel und Feldbeschriftungen in Layout-Reihenfolge', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({ name: 'Marco', ort: 'Köln', anlass: 'kunde' }))
    const all = texts().map((t) => t.text)
    expect(all[0]).toBe('Hotelbuchung')
    expect(all[1]).toBe('Reise nach Köln')
    expect(all).toContain('Auftrag #128')
    expect(all).toContain('Erstellt von: Marco Schneider')
    expect(all).toContain('Angelegt: 10.08.2026 09:05 Uhr')
    // Reihenfolge: Abschnitt, dann seine Felder.
    const idx = (s: string) => all.indexOf(s)
    expect(idx('Antragsteller')).toBeGreaterThan(idx('Reise nach Köln'))
    expect(idx('NAME')).toBeGreaterThan(idx('Antragsteller'))
    expect(idx('ORT')).toBeGreaterThan(idx('NAME'))
    expect(idx('ANLASS')).toBeGreaterThan(idx('ORT'))
    expect(idx('Details')).toBeGreaterThan(idx('ANLASS'))
  })

  it('stellt die Spalten an die Position, die die Layout-Breite vorgibt', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({ name: 'Marco', ort: 'Köln', anlass: 'kunde' }))
    const at = (s: string) => texts().find((t) => t.text === s)!
    // Inhaltsbreite 178 mm: quarter (3/12) links, third (4/12) daneben,
    // twothirds (8/12) passt nicht mehr in dieselbe Rasterzeile.
    expect(at('NAME').x).toBeCloseTo(16, 5)
    expect(at('ORT').x).toBeCloseTo(16 + (3 / 12) * 178, 5)
    expect(at('ANLASS').x).toBeCloseTo(16, 5)
    expect(at('ANLASS').y).toBeGreaterThan(at('NAME').y)
    // Gleiche Rasterzeile → gleiche Grundlinie.
    expect(at('ORT').y).toBeCloseTo(at('NAME').y, 5)
  })

  it('zeichnet den Farbbalken der Variante statt eines Emoji-Icons', () => {
    const { pdf, calls, texts } = fakePdf()
    drawExportDoc(pdf, build({ name: 'Marco' }))
    // hr = blau (59,130,246): erst Farbe setzen, dann der 2,6 mm breite Balken.
    const fills = calls.filter((c) => c.fn === 'setFillColor').map((c) => c.args.join(','))
    expect(fills).toContain('59,130,246')
    expect(calls.some((c) => c.fn === 'rect' && c.args[2] === 2.6)).toBe(true)
    // Kein Emoji im gesetzten Text.
    expect(texts().every((t) => !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(t.text))).toBe(true)
  })

  it('stutzt überlange Namen, damit Kopfspalten sich nicht überschreiben', () => {
    const { pdf, texts } = fakePdf()
    const lang = 'Sehr langer Prozessname '.repeat(12).trim()
    drawExportDoc(pdf, build({}, { meta: { ...META, processName: lang } }))
    const title = texts()[0].text
    expect(title.endsWith('...')).toBe(true)
    expect(title.length).toBeLessThan(lang.length)
    // Die Kopfdaten rechts bleiben vollständig.
    expect(texts().map((t) => t.text)).toContain('Auftrag #128')
  })

  it('schreibt „Nicht angegeben" statt eines leeren Wertes', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({ name: 'Marco' }))
    expect(texts().filter((t) => t.text === 'Nicht angegeben').length).toBeGreaterThan(0)
  })

  it('rückt Wiederholgruppen als beschriftete Blöcke ein', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({ naechte: [{ datum: '2026-09-01', preis: 119 }] }))
    const all = texts()
    const entry = all.find((t) => t.text === 'EINTRAG 1')!
    expect(entry).toBeTruthy()
    expect(entry.x).toBeCloseTo(20, 5)          // 16 mm Rand + 4 mm Einrückung
    expect(all.map((t) => t.text)).toContain('Datum: 01.09.2026')
    expect(all.map((t) => t.text)).toContain('Preis: 119')
  })

  it('nennt Anhänge beim Namen und verschweigt fehlende nicht', () => {
    const withFiles = fakePdf()
    drawExportDoc(withFiles.pdf, build({}, { attachments: { belege: ['rechnung.pdf'] } }))
    expect(withFiles.texts().map((t) => t.text)).toContain('- rechnung.pdf')

    const without = fakePdf()
    drawExportDoc(without.pdf, build({}))
    expect(without.texts().some((t) => t.text.includes('nicht Teil dieses Ausdrucks'))).toBe(true)
  })

  it('ersetzt das Ton-Symbol der Hinweisbox durch sein Wort', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({}))
    expect(texts().map((t) => t.text)).toContain('ACHTUNG')
    expect(texts().map((t) => t.text)).toContain('Bitte Budget beachten')
  })

  it('bricht bei langem Inhalt um und wiederholt die Beschriftung', () => {
    const { pdf, texts, pageCount } = fakePdf()
    const lang = Array.from({ length: 400 }, (_, i) => `Zeile${i}`).join(' ')
    drawExportDoc(pdf, build({ begruendung: lang }))
    expect(pageCount()).toBeGreaterThan(1)
    expect(texts().map((t) => t.text)).toContain('BEGRÜNDUNG (FORTSETZUNG)')
    // Die Fortsetzung steht auf einer späteren Seite als die Beschriftung.
    const first = texts().find((t) => t.text === 'BEGRÜNDUNG')!
    const cont = texts().find((t) => t.text === 'BEGRÜNDUNG (FORTSETZUNG)')!
    expect(cont.page).toBeGreaterThan(first.page)
  })

  it('setzt Fußzeile und Seitenzahl auf jede Seite', () => {
    const { pdf, texts, pageCount } = fakePdf()
    const lang = Array.from({ length: 400 }, (_, i) => `Zeile${i}`).join(' ')
    drawExportDoc(pdf, build({ begruendung: lang }))
    const n = pageCount()
    for (let i = 1; i <= n; i++) {
      expect(texts().some((t) => t.text === `Seite ${i} / ${n}`)).toBe(true)
    }
    expect(texts().some((t) => t.text === 'Hotelbuchung - #128 - Marco Schneider')).toBe(true)
  })

  it('setzt die Fußnote zur Sichtbarkeit ans Ende des Fließtextes', () => {
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, build({ name: 'Marco' }))
    expect(texts().some((t) => t.text.includes('freigegeben'))).toBe(true)
  })

  it('sagt es, wenn gar nichts zu drucken ist', () => {
    const definition = demoDefinition()
    const doc = buildExportDoc({
      definition, phase: null, values: {}, viewer: VIEWER, meta: META,
    })
    const { pdf, texts } = fakePdf()
    drawExportDoc(pdf, doc)
    expect(texts().map((t) => t.text)).toContain('Keine sichtbaren Angaben.')
  })
})

// ── Kleinkram ────────────────────────────────────────────────────────────────

describe('formatTimestamp', () => {
  it('formatiert ohne Zeitzonen-Verschiebung', () => {
    expect(formatTimestamp('2026-08-10T09:05:00')).toBe('10.08.2026 09:05 Uhr')
    expect(formatTimestamp('2026-08-10')).toBe('10.08.2026')
    expect(formatTimestamp(null)).toBe('—')
    expect(formatTimestamp('kaputt')).toBe('kaputt')
  })
})

describe('exportFileName', () => {
  it('schreibt Umlaute um und ersetzt alles Übrige', () => {
    expect(exportFileName({ ...META, processName: 'Büro-Ausstattung', ticketNumber: '#7' }))
      .toBe('Buero_Ausstattung_7.pdf')
  })

  it('kommt ohne Auftragsnummer aus', () => {
    expect(exportFileName({ ...META, ticketNumber: null })).toBe('Hotelbuchung.pdf')
  })

  it('fällt auf einen Namen zurück, wenn nichts Brauchbares übrig bleibt', () => {
    expect(exportFileName({ ...META, processName: '???', ticketNumber: null }))
      .toBe('Auftrag.pdf')
  })
})
