/**
 * Auswertung des Seed-Berichts.
 *
 * Warum das getestet wird: der Trockenlauf ist die einzige Entscheidungsgrundlage
 * vor dem Schreiben. Ein Bericht, der Zeilen verschluckt oder eine Kopfzeile
 * zeigt, die der Liste widerspricht, würde genau die Frage falsch beantworten,
 * für die es den Knopf gibt. Kein Mounting – das Projekt hat kein jsdom.
 */
import { describe, it, expect } from 'vitest'
import {
  normalizeSeedReport, permissionsSummary, seedHeadline,
} from './processSeedReport'

/** Antwort, wie sie der Endpunkt liefert (api/v1/processes.py: SeedReportOut). */
const TROCKENLAUF = {
  commit: false,
  created: 2,
  skipped: 2,
  errors: 1,
  required_groups: ['IT', 'Personal', 'Einkauf'],
  created_groups: [],
  missing_groups: ['Einkauf'],
  outcomes: [
    {
      file: 'prozess-basis-ticket.json',
      key: 'basis-ticket',
      action: 'skipped',
      message: 'System-Prozess – wird beim Start automatisch angelegt und aktuell gehalten',
      warnings: [],
      create_permissions: null,
      ineffective_groups: [],
    },
    {
      file: 'prozess-onboarding.json',
      key: 'onboarding',
      action: 'would_create',
      message: 'würde angelegt und veröffentlicht',
      warnings: ['Platzhalter im Text bei phases[0].title: „{{IT}}“'],
      create_permissions: { everyone: false, groups: ['g-it'], users: ['u1', 'u2'] },
      ineffective_groups: ['ad-alle-mitarbeitenden'],
    },
    {
      file: 'prozess-bestellung.json',
      key: 'bestellung',
      action: 'would_create',
      message: 'würde angelegt und veröffentlicht',
      warnings: [],
      create_permissions: { everyone: true, groups: [], users: [] },
      ineffective_groups: [],
    },
    {
      file: 'prozess-hardware.json',
      key: 'hardware',
      action: 'skipped',
      message: 'Schlüssel existiert bereits (v1/published) – nichts überschrieben',
      warnings: [],
      create_permissions: null,
      ineffective_groups: [],
    },
    {
      file: 'prozess-kaputt.json',
      key: 'kaputt',
      action: 'error',
      message: 'Gruppen-Referenzen kaputt – nicht eingespielt',
      warnings: [],
      create_permissions: null,
      ineffective_groups: [],
    },
  ],
}

describe('normalizeSeedReport', () => {
  it('liest den Bericht des Endpunkts vollständig', () => {
    const s = normalizeSeedReport(TROCKENLAUF)
    expect(s.commit).toBe(false)
    expect(s.rows).toHaveLength(5)
    expect(s.requiredGroups).toEqual(['IT', 'Personal', 'Einkauf'])
    expect(s.missingGroups).toEqual(['Einkauf'])
    expect(s.createdGroups).toEqual([])
    expect(s.counts).toEqual({ created: 2, skipped: 2, errors: 1, total: 5 })
    expect(s.hasErrors).toBe(true)
    expect(s.nothingToDo).toBe(false)
  })

  it('behält die Reihenfolge des Laufs (wie die CLI-Ausgabe)', () => {
    expect(normalizeSeedReport(TROCKENLAUF).rows.map((r) => r.key)).toEqual(
      ['basis-ticket', 'onboarding', 'bestellung', 'hardware', 'kaputt'])
  })

  it('beschriftet jede Aktion in Klartext und mit passendem Ton', () => {
    const byKey = new Map(normalizeSeedReport(TROCKENLAUF).rows.map((r) => [r.key, r]))
    expect(byKey.get('onboarding')!.label).toBe('wird angelegt')
    expect(byKey.get('onboarding')!.tone).toBe('info')
    expect(byKey.get('hardware')!.label).toBe('übersprungen')
    expect(byKey.get('hardware')!.tone).toBe('muted')
    expect(byKey.get('kaputt')!.label).toBe('Fehler')
    expect(byKey.get('kaputt')!.tone).toBe('error')
    expect(normalizeSeedReport({ outcomes: [{ file: 'x.json', key: 'x', action: 'created' }] })
      .rows[0]).toMatchObject({ label: 'angelegt', tone: 'ok' })
  })

  it('übernimmt Warnungen, wirkungslose Gruppen und Erstellrechte je Zeile', () => {
    const r = normalizeSeedReport(TROCKENLAUF).rows[1]
    expect(r.warnings).toHaveLength(1)
    expect(r.ineffectiveGroups).toEqual(['ad-alle-mitarbeitenden'])
    expect(r.permissions).toEqual({ everyone: false, groups: ['g-it'], users: ['u1', 'u2'] })
  })

  it('zählt aus den Zeilen, nicht aus den Server-Summen', () => {
    // Sonst könnte eine Kopfzeile „9 angelegt“ über einer Liste stehen, in der
    // nichts angelegt wird – die Zeilen sind die Wahrheit.
    const s = normalizeSeedReport({
      commit: true, created: 9, skipped: 0, errors: 0,
      outcomes: [{ file: 'a.json', key: 'a', action: 'skipped', message: 'da' }],
    })
    expect(s.counts).toEqual({ created: 0, skipped: 1, errors: 0, total: 1 })
    expect(s.headline).toBe('Eingespielt: 0 angelegt, 1 übersprungen.')
  })

  it('führt eine unbekannte Aktion als Fehler – nicht als Erfolg', () => {
    const s = normalizeSeedReport({ outcomes: [{ file: 'a.json', key: 'a', action: 'huch' }] })
    expect(s.rows[0].action).toBe('error')
    expect(s.rows[0].label).toBe('unbekannt (huch)')
    expect(s.hasErrors).toBe(true)
  })

  it('nimmt auch die deutschen Feldnamen des Dataclass an', () => {
    // Ein direkt serialisiertes SeedOutcome (services/seed_definitions.py) darf
    // nicht in einer leeren Tabelle enden.
    const s = normalizeSeedReport({
      commit: true,
      pflichtgruppen: ['IT'],
      angelegte_gruppen: ['Einkauf'],
      fehlende_gruppen: [],
      outcomes: [{
        datei: 'prozess-onboarding.json', key: 'onboarding', aktion: 'created',
        meldung: 'angelegt und veröffentlicht', warnungen: ['achtung'],
        createPermissions: { everyone: false, groups: ['g1'], users: [] },
        wirkungslose_gruppen: ['ad-x'],
      }],
    })
    expect(s.requiredGroups).toEqual(['IT'])
    expect(s.createdGroups).toEqual(['Einkauf'])
    expect(s.rows[0]).toMatchObject({
      title: 'onboarding',
      file: 'prozess-onboarding.json',
      action: 'created',
      message: 'angelegt und veröffentlicht',
      warnings: ['achtung'],
      ineffectiveGroups: ['ad-x'],
    })
    expect(s.rows[0].permissions).toEqual({ everyone: false, groups: ['g1'], users: [] })
  })

  it('wickelt eine data-Hülle aus', () => {
    const s = normalizeSeedReport({ data: { commit: false, outcomes: [{ file: 'a.json', key: 'a', action: 'would_create' }] } })
    expect(s.rows).toHaveLength(1)
  })

  it('markiert System-Zeilen, wenn der Server es mitschickt', () => {
    const s = normalizeSeedReport({
      outcomes: [
        { file: 'a.json', key: 'basis-ticket', action: 'skipped', is_system: true },
        { file: 'b.json', key: 'onboarding', action: 'would_create' },
      ],
    })
    expect(s.rows.map((r) => r.isSystem)).toEqual([true, false])
  })

  it('benennt eine Zeile ohne Schlüssel nach der Datei', () => {
    const s = normalizeSeedReport({
      outcomes: [
        { file: 'kaputt.json', action: 'error', message: 'Definition hat keinen `key`' },
        { action: 'error', message: 'nicht lesbar' },
      ],
    })
    expect(s.rows[0].title).toBe('kaputt.json')
    expect(s.rows[0].key).toBeNull()
    expect(s.rows[1].title).toBe('(ohne Schlüssel)')
  })

  it('überlebt Müll, ohne zu werfen', () => {
    for (const müll of [null, undefined, 42, 'nein', [], {}, { outcomes: 'kaputt' }]) {
      const s = normalizeSeedReport(müll)
      expect(s.rows).toEqual([])
      expect(s.counts.total).toBe(0)
      expect(s.nothingToDo).toBe(true)
    }
    // Nicht-Objekte in der Liste werden übersprungen, nicht als Zeile gezeigt.
    expect(normalizeSeedReport({ outcomes: [null, 'x', { file: 'a.json', key: 'a', action: 'created' }] })
      .rows).toHaveLength(1)
    // Fremdtypen in Textlisten fliegen raus statt als „[object Object]“ zu erscheinen.
    expect(normalizeSeedReport({ required_groups: ['IT', 7, null, '  '] }).requiredGroups)
      .toEqual(['IT'])
  })

  it('erkennt „nichts zu tun“ – dann lohnt kein Einspielen', () => {
    const s = normalizeSeedReport({
      commit: false,
      outcomes: [
        { file: 'a.json', key: 'a', action: 'skipped', message: 'existiert' },
        { file: 'b.json', key: 'basis-ticket', action: 'skipped', message: 'System-Prozess' },
      ],
    })
    expect(s.nothingToDo).toBe(true)
    expect(s.hasErrors).toBe(false)
  })
})

describe('seedHeadline', () => {
  it('sagt beim Trockenlauf ausdrücklich, dass nichts geschrieben wurde', () => {
    expect(seedHeadline(false, { created: 9, skipped: 1, errors: 0, total: 10 }))
      .toBe('Trockenlauf – es wurde nichts geschrieben: 9 würden angelegt, 1 übersprungen.')
  })

  it('zählt Fehler nur, wenn es welche gibt', () => {
    expect(seedHeadline(true, { created: 8, skipped: 1, errors: 1, total: 10 }))
      .toBe('Eingespielt: 8 angelegt, 1 übersprungen, 1 Fehler.')
    expect(seedHeadline(true, { created: 7, skipped: 1, errors: 2, total: 10 }))
      .toBe('Eingespielt: 7 angelegt, 1 übersprungen, 2 Fehler.')
  })
})

describe('permissionsSummary', () => {
  it('fasst zusammen, wer anlegen dürfte', () => {
    expect(permissionsSummary({ everyone: true, groups: ['g1'], users: ['u1', 'u2'] }))
      .toBe('alle Angemeldeten · 1 Fachabteilung · 2 Personen')
    expect(permissionsSummary({ everyone: false, groups: ['g1', 'g2'], users: ['u1'] }))
      .toBe('2 Fachabteilungen · 1 Person')
  })

  it('nennt leere Rechte beim Namen: nur Admins', () => {
    // Genau der Fall „Installation ohne Alt-Daten“ – muss sichtbar sein, sonst
    // wundert sich später jemand, warum niemand anlegen kann.
    expect(permissionsSummary({ everyone: false, groups: [], users: [] })).toBe('nur Admins')
  })

  it('ohne Angabe keine Zeile (übersprungene Prozesse setzen keine Rechte)', () => {
    expect(permissionsSummary(null)).toBeNull()
  })
})
