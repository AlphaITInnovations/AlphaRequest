/**
 * Die Übersicht bekommt IDs und muss Namen zeigen – oder ehrlich den Rohwert.
 *
 * Der teure Fehler wäre eine erfundene Beschriftung: ein unbekannter Prozess-Key
 * als „—", ein leeres Zuständigkeits-Feld als „Ersteller:in". Beides wäre eine
 * Falschaussage über den echten Stand, deshalb hier festgenagelt.
 */
import { describe, expect, it } from 'vitest'
import { buildLookup, formatDateTime, LEER, toOverviewRow, toOverviewRows } from '@/lib/overviewRow'

const KATALOG = [
  { key: 'hardware', name: 'Hardwarebestellung', icon: '📦' },
  { key: 'basis-ticket', name: 'Basis-Ticket', icon: null },
]
const GRUPPEN = [{ id: 'fach-it', name: 'IT' }]
const PERSONEN = [{ id: 'u-1', displayName: 'Anna Admin' }]
const LOOK = buildLookup({ catalog: KATALOG, groups: GRUPPEN, users: PERSONEN })

describe('toOverviewRow – Beschriftungen', () => {
  it('nimmt Name und Symbol aus dem Katalog', () => {
    const r = toOverviewRow({ id: 7, title: 'Notebook', process_key: 'hardware' }, LOOK)
    expect(r.processLabel).toBe('Hardwarebestellung')
    expect(r.processIcon).toBe('📦')
  })

  it('zeigt einen unbekannten Prozess ROH (nie erfunden)', () => {
    const r = toOverviewRow({ id: 7, process_key: 'gibt-es-nicht' }, LOOK)
    expect(r.processLabel).toBe('gibt-es-nicht')
    expect(r.processIcon).toBe('')
  })

  it('zeigt einen unbekannten Status roh, einen bekannten deutsch', () => {
    expect(toOverviewRow({ id: 1, status: 'in_request' }).statusLabel).toBe('In Prüfung')
    expect(toOverviewRow({ id: 1, status: 'neu_erfunden' }).statusLabel).toBe('neu_erfunden')
  })

  it('füllt fehlende Angaben mit demselben Platzhalter', () => {
    const r = toOverviewRow({ id: 3 })
    expect([r.phaseLabel, r.ownerName, r.createdAt, r.processLabel]).toEqual([LEER, LEER, LEER, LEER])
  })

  it('gibt einem Auftrag ohne Titel einen erkennbaren Ersatz', () => {
    expect(toOverviewRow({ id: 9, title: '   ' }).title).toBe('Auftrag #9')
  })
})

describe('toOverviewRow – Zuständigkeit', () => {
  it('löst die Fachabteilung über die Gruppenliste auf', () => {
    const r = toOverviewRow({ id: 1, responsibility: { kind: 'group', group: 'fach-it' } }, LOOK)
    expect(r.responsible.text).toBe('IT')
    expect(r.responsible.missing).toBe(false)
  })

  it('zeigt eine unbekannte Gruppen-ID roh, statt sie zu verschweigen', () => {
    const r = toOverviewRow({ id: 1, responsibility: { kind: 'group', group: 'fach-neu' } }, LOOK)
    expect(r.responsible.text).toBe('fach-neu')
  })

  it('nennt die Person mit Namen', () => {
    const r = toOverviewRow({ id: 1, responsibility: { kind: 'user', user: 'u-1' } }, LOOK)
    expect(r.responsible.text).toBe('Anna Admin')
  })

  it('nimmt bei kind=owner den Namen aus dem Auftrag', () => {
    const r = toOverviewRow(
      { id: 1, owner_name: 'Bert Bauer', responsibility: { kind: 'owner' } }, LOOK)
    expect(r.responsible.text).toBe('Bert Bauer')
    expect(r.responsible.missing).toBe(false)
  })

  it('macht „niemand zuständig" sichtbar – mit Begründung', () => {
    // Leeres Quellfeld: der Auftrag bleibt liegen, das MUSS in der Liste auffallen.
    const r = toOverviewRow({
      id: 1, responsibility: { kind: 'user', user: null, from_field: 'antrag.bearbeiter' },
    }, LOOK)
    expect(r.responsible.missing).toBe(true)
    expect(r.responsible.text).toBe('')
    expect(r.responsible.hint).toContain('antrag.bearbeiter')
  })

  it('zählt Fachabteilungen zusammen, statt sie alle aufzuzählen', () => {
    const r = toOverviewRow({
      id: 1,
      responsibility: {
        kind: 'departments',
        departments: [{ group: 'fach-it' }, { group: 'fach-hr' }],
      },
    }, LOOK)
    expect(r.responsible.text).toBe('2 Fachabteilungen')
  })
})

describe('formatDateTime', () => {
  it('meldet fehlende Zeitstempel als Platzhalter', () => {
    expect(formatDateTime(null)).toBe(LEER)
    expect(formatDateTime('')).toBe(LEER)
  })

  it('gibt einen unlesbaren Wert ROH zurück', () => {
    expect(formatDateTime('kein Datum')).toBe('kein Datum')
  })

  it('liest den naiven Serverwert als UTC (gleiche Ausgabe wie mit „Z")', () => {
    expect(formatDateTime('2026-08-14T10:30:00')).toBe(formatDateTime('2026-08-14T10:30:00Z'))
  })
})

describe('buildLookup', () => {
  it('fällt ohne Listen auf die Rohwerte zurück', () => {
    const leer = buildLookup({})
    expect(leer.groupName?.('fach-it')).toBe('fach-it')
    expect(leer.userName?.('u-1')).toBe('u-1')
    expect(leer.processName?.('hardware')).toBeUndefined()
  })

  it('bildet mehrere Zeilen in einem Durchgang ab', () => {
    const rows = toOverviewRows([{ id: 1, process_key: 'hardware' }, { id: 2 }], LOOK)
    expect(rows.map((r) => r.id)).toEqual([1, 2])
  })
})
