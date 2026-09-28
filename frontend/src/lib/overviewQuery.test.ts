/**
 * Die Übersicht darf nie behaupten, ein Fenster sei das Gesamtergebnis.
 *
 * Geprüft wird deshalb vor allem die Grenze zwischen „der Server filtert" und
 * „der Client filtert": genau EIN Status geht an den Server (vollständig,
 * geblättert), mehrere Status / Arbeitslisten / abweichende Sortierung landen im
 * Scan-Modus – und der muss als unvollständig erkennbar sein.
 */
import { describe, expect, it } from 'vitest'
import {
  applyScope, defaultStatuses, filterByStatus, inScope, isServerOrder,
  isWindowTruncated, OVERVIEW_STATUSES, pageCount, pageSlice, parseTicketRef,
  planQuery, sortTickets, statusAllowsEverything, statusNeedsClient, statusServerParam,
  type OverviewFilterState, type PlanOptions, type ScopeTicket,
} from '@/lib/overviewQuery'

const OPTS: PlanOptions = { page: 1, pageSize: 25, scanLimit: 200 }

function filter(over: Partial<OverviewFilterState> = {}): OverviewFilterState {
  return {
    scope: 'all',
    statuses: [...OVERVIEW_STATUSES],
    q: '',
    processKey: '',
    sortKey: 'updated_at',
    sortDir: 'desc',
    ...over,
  }
}

// ── Status ────────────────────────────────────────────────────────────────────

describe('Status-Auswahl', () => {
  it('blendet in der Startauswahl nur „Archiviert" aus', () => {
    expect(defaultStatuses()).toEqual(['in_progress', 'in_request', 'waiting_contract', 'rejected'])
  })

  it('erkennt „alles ausgewählt" als filterfrei', () => {
    expect(statusAllowsEverything([...OVERVIEW_STATUSES])).toBe(true)
    expect(statusNeedsClient([...OVERVIEW_STATUSES])).toBe(false)
    expect(statusServerParam([...OVERVIEW_STATUSES])).toBeUndefined()
  })

  it('gibt genau EINEN Status an den Server, mehrere an den Client', () => {
    expect(statusServerParam(['archived'])).toBe('archived')
    expect(statusNeedsClient(['archived'])).toBe(false)
    expect(statusServerParam(['archived', 'rejected'])).toBeUndefined()
    expect(statusNeedsClient(['archived', 'rejected'])).toBe(true)
  })

  it('behandelt Doppelungen wie eine Auswahl', () => {
    expect(statusServerParam(['archived', 'archived'])).toBe('archived')
  })

  it('leere Auswahl ist ein Client-Filter (und zeigt nichts)', () => {
    expect(statusNeedsClient([])).toBe(true)
    expect(filterByStatus([{ status: 'in_progress' }], [])).toEqual([])
  })

  it('lässt einen unbekannten Status stehen, wenn „alles" gewählt ist', () => {
    // Neuer Server, alte Oberfläche: der Auftrag darf nicht still verschwinden.
    const rows = [{ status: 'in_progress' }, { status: 'irgendwas_neues' }]
    expect(filterByStatus(rows, [...OVERVIEW_STATUSES])).toHaveLength(2)
    expect(filterByStatus(rows, ['in_progress', 'rejected'])).toEqual([{ status: 'in_progress' }])
  })
})

// ── Plan ──────────────────────────────────────────────────────────────────────

describe('planQuery', () => {
  it('blättert serverseitig, wenn der Server alles kann', () => {
    const plan = planQuery(filter(), { ...OPTS, page: 3 })
    expect(plan.mode).toBe('server')
    expect(plan.clientSide).toEqual([])
    expect(plan.params).toEqual({ limit: 25, offset: 50 })
  })

  it('nennt jede clientseitige Nachbearbeitung', () => {
    const plan = planQuery(
      filter({ statuses: defaultStatuses(), scope: 'assigned', sortKey: 'title', sortDir: 'asc' }),
      OPTS)
    expect(plan.mode).toBe('scan')
    expect(plan.clientSide).toEqual(['status', 'scope', 'sort'])
  })

  it('lädt im Scan-Modus immer den Anfang des Fensters', () => {
    const plan = planQuery(filter({ scope: 'created' }), { ...OPTS, page: 4 })
    expect(plan.params).toEqual({ limit: 200, offset: 0 })
  })

  it('gibt Status, Prozess und Suche serverseitig weiter (getrimmt)', () => {
    const plan = planQuery(filter({ statuses: ['in_request'], processKey: ' hardware ', q: '  Büro ' }),
                           OPTS)
    expect(plan.mode).toBe('server')
    expect(plan.params).toEqual({
      limit: 25, offset: 0, status: 'in_request', process_key: 'hardware', q: 'Büro',
    })
  })

  it('lässt leere Filter ganz weg (sonst filtert der Server auf Leerstring)', () => {
    const plan = planQuery(filter({ q: '   ', processKey: '' }), OPTS)
    expect(plan.params.q).toBeUndefined()
    expect(plan.params.process_key).toBeUndefined()
  })

  it('kennt die einzige Server-Sortierung', () => {
    expect(isServerOrder('updated_at', 'desc')).toBe(true)
    expect(isServerOrder('updated_at', 'asc')).toBe(false)
    expect(isServerOrder('id', 'desc')).toBe(false)
  })
})

describe('isWindowTruncated', () => {
  const scan = planQuery(filter({ scope: 'assigned' }), OPTS)
  const server = planQuery(filter(), OPTS)

  it('meldet ein abgeschnittenes Fenster', () => {
    expect(isWindowTruncated(scan, 640, 200)).toBe(true)
  })

  it('meldet nichts, wenn das Fenster alles enthält', () => {
    // Auch dann korrekt, wenn der Server Zeilen wegen Sichtbarkeit entfernt hat:
    // meta.total ist um genau diese vermindert.
    expect(isWindowTruncated(scan, 40, 40)).toBe(false)
  })

  it('hält weitere Seiten im Server-Modus NICHT für Unvollständigkeit', () => {
    expect(isWindowTruncated(server, 640, 25)).toBe(false)
  })
})

// ── Sichten ───────────────────────────────────────────────────────────────────

const ICH = 'u-ich'
const CTX = { userId: ICH, groupIds: ['fach-it', 'fach-hr'] }

function ticket(over: Partial<ScopeTicket> = {}): ScopeTicket {
  return { owner_id: 'u-andere', status: 'in_progress', runtime: { rejected: false }, ...over }
}

describe('inScope', () => {
  it('„Alle" lässt jeden Auftrag durch', () => {
    expect(inScope(ticket({ status: 'archived' }), 'all', CTX)).toBe(true)
  })

  it('„Mir zugewiesen" trifft die persönliche Zuständigkeit', () => {
    expect(inScope(ticket({ responsibility: { kind: 'user', user: ICH } }), 'assigned', CTX))
      .toBe(true)
    expect(inScope(ticket({ responsibility: { kind: 'user', user: 'u-x' } }), 'assigned', CTX))
      .toBe(false)
  })

  it('„Mir zugewiesen" zählt auch mit, wenn ich als Ersteller:in am Zug bin', () => {
    expect(inScope(ticket({ owner_id: ICH, responsibility: { kind: 'owner' } }), 'assigned', CTX))
      .toBe(true)
    expect(inScope(ticket({ responsibility: { kind: 'owner' } }), 'assigned', CTX)).toBe(false)
  })

  it('„Meine Abteilungen" fragt den LIVE-Stand der Fachabteilungen', () => {
    const offen = ticket({
      responsibility: {
        kind: 'departments',
        departments: [{ group: 'fach-it', status: 'open' }, { group: 'fach-x', status: 'open' }],
      },
    })
    const erledigt = ticket({
      responsibility: {
        kind: 'departments',
        departments: [{ group: 'fach-it', status: 'done' }],
      },
    })
    expect(inScope(offen, 'departments', CTX)).toBe(true)
    expect(inScope(erledigt, 'departments', CTX)).toBe(false)
  })

  it('Arbeitslisten lassen terminale Aufträge liegen', () => {
    const resp = { kind: 'user', user: ICH }
    expect(inScope(ticket({ responsibility: resp, status: 'archived' }), 'assigned', CTX))
      .toBe(false)
    expect(inScope(ticket({ responsibility: resp, runtime: { rejected: true } }), 'assigned', CTX))
      .toBe(false)
  })

  it('„Von mir angelegt" behält abgeschlossene Aufträge (Archiv, keine Arbeitsliste)', () => {
    expect(inScope(ticket({ owner_id: ICH, status: 'archived' }), 'created', CTX)).toBe(true)
    expect(inScope(ticket({ owner_id: 'u-andere' }), 'created', CTX)).toBe(false)
  })

  it('„Beteiligt" sind laufende Aufträge ANDERER', () => {
    expect(inScope(ticket(), 'involved', CTX)).toBe(true)
    expect(inScope(ticket({ owner_id: ICH }), 'involved', CTX)).toBe(false)
    expect(inScope(ticket({ status: 'rejected' }), 'involved', CTX)).toBe(false)
  })

  it('ohne Personen-ID bleiben die persönlichen Sichten leer, statt zu raten', () => {
    const ohne = { userId: null, groupIds: [] }
    for (const scope of ['assigned', 'departments', 'created', 'involved'] as const) {
      expect(inScope(ticket({ owner_id: ICH }), scope, ohne)).toBe(false)
    }
    expect(inScope(ticket(), 'all', ohne)).toBe(true)
  })
})

describe('applyScope', () => {
  it('behält die Reihenfolge des Servers', () => {
    const rows = [
      ticket({ owner_id: ICH, status: 'in_progress' }),
      ticket({ owner_id: 'u-andere' }),
      ticket({ owner_id: ICH, status: 'archived' }),
    ]
    expect(applyScope(rows, 'created', CTX)).toEqual([rows[0], rows[2]])
  })
})

// ── Sortierung & Blätterung ───────────────────────────────────────────────────

describe('sortTickets', () => {
  const rows = [
    { id: 1, title: 'Zebra', owner_name: 'Anna', status: 'archived', created_at: '2026-01-01', updated_at: '2026-05-01' },
    { id: 2, title: 'apfel', owner_name: 'Bert', status: 'in_progress', created_at: '2026-03-01', updated_at: '2026-04-01' },
    { id: 3, title: 'Möhre', owner_name: 'anna', status: 'in_request', created_at: '2026-02-01', updated_at: '2026-06-01' },
  ]

  it('sortiert Titel ohne Rücksicht auf Groß-/Kleinschreibung', () => {
    expect(sortTickets(rows, 'title', 'asc').map((r) => r.id)).toEqual([2, 3, 1])
  })

  it('sortiert Status nach Bearbeitungsstand, nicht alphabetisch', () => {
    expect(sortTickets(rows, 'status', 'asc').map((r) => r.id)).toEqual([2, 3, 1])
  })

  it('sortiert Zahlen als Zahlen und dreht die Richtung', () => {
    expect(sortTickets(rows, 'id', 'desc').map((r) => r.id)).toEqual([3, 2, 1])
  })

  it('hält bei Gleichstand die Reihenfolge des Servers', () => {
    const gleich = [{ id: 5, owner_name: 'Anna' }, { id: 4, owner_name: 'anna' }]
    expect(sortTickets(gleich, 'owner', 'asc').map((r) => r.id)).toEqual([5, 4])
  })

  it('lässt die Vorlage unangetastet', () => {
    const kopie = [...rows]
    sortTickets(rows, 'id', 'asc')
    expect(rows).toEqual(kopie)
  })
})

describe('Blätterung', () => {
  it('zählt mindestens eine Seite', () => {
    expect(pageCount(0, 25)).toBe(1)
    expect(pageCount(26, 25)).toBe(2)
    expect(pageCount(50, 25)).toBe(2)
  })

  it('schneidet die richtige Seite heraus', () => {
    const rows = [1, 2, 3, 4, 5]
    expect(pageSlice(rows, 1, 2)).toEqual([1, 2])
    expect(pageSlice(rows, 3, 2)).toEqual([5])
    expect(pageSlice(rows, 9, 2)).toEqual([])
    expect(pageSlice(rows, 0, 2)).toEqual([1, 2])
  })
})

// ── Direktsprung ──────────────────────────────────────────────────────────────

describe('parseTicketRef', () => {
  it('erkennt Auftragsnummern mit und ohne Raute', () => {
    expect(parseTicketRef('42')).toBe(42)
    expect(parseTicketRef(' #42 ')).toBe(42)
  })

  it('erkennt Titel-Suchen NICHT als Nummer', () => {
    expect(parseTicketRef('Notebook 42')).toBeNull()
    expect(parseTicketRef('#0')).toBeNull()
    expect(parseTicketRef('')).toBeNull()
    expect(parseTicketRef('#12a')).toBeNull()
  })
})
