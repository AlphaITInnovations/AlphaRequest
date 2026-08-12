import { describe, it, expect } from 'vitest'
import example from '../../../docs/examples/prozess-hotelbuchung.json'
import { normalizeDefinition } from './processNormalize'
import { errorCount, validateDefinition } from './processValidate'
import { renderFields, validatePhaseCompletion } from './processSim'
import type { SimViewer } from './processSim'

/**
 * Das Beispiel in docs/examples/ soll importierbar BLEIBEN. Ändert sich das
 * Format oder eine Whitelist, schlägt dieser Test fehl statt dass jemand beim
 * Import in einen 422 läuft.
 */
const DEFN = normalizeDefinition(example)
const OWNER: SimViewer = { fullView: true, isAdmin: false, groupIds: [] }

describe('Beispiel-Prozess Hotelbuchung', () => {
  it('ist ohne Fehler gültig (Gruppen-Platzhalter erzeugen nur Hinweise)', () => {
    const issues = validateDefinition(DEFN)
    expect(errorCount(issues)).toBe(0)
  })

  it('hat den erwarteten Ablauf', () => {
    expect(DEFN.phases.map((p) => p.key)).toEqual(['erstellung', 'durchfuehrung', 'reisestelle'])
    expect(DEFN.phases[0].kind).toBe('start')
    expect(DEFN.phases[1].responsibility.kind).toBe('departments')
    expect(DEFN.phases[2].responsibility.kind).toBe('group')
  })

  it('zeigt die Kundentermin-Felder nur beim passenden Reiseanlass', () => {
    const start = DEFN.phases[0]
    const off = renderFields(DEFN, start, { 'buchung.reiseanlass': 'sonstiges' }, OWNER)
    expect(off.find((r) => r.ref.ref === 'buchung.kunde_name')!.visible).toBe(false)

    const on = renderFields(DEFN, start, { 'buchung.reiseanlass': 'kundentermin' }, OWNER)
    const kunde = on.find((r) => r.ref.ref === 'buchung.kunde_name')!
    expect(kunde.visible).toBe(true)
    expect(kunde.required).toBe(true)
  })

  it('verlangt die Budget-Begründung nur bei Abweichung', () => {
    const start = DEFN.phases[0]
    const base = {
      'buchung.antragsteller_name': 'Muster, Max',
      'buchung.antragsteller_email': 'max@example.org',
      'buchung.niederlassung': 'Hamburg',
      'buchung.telefonnummer': '+49 40 123',
      'buchung.kostenstelle': '1234',
      'buchung.anreisedatum': '2026-09-01',
      'buchung.abreisedatum': '2026-09-03',
      'buchung.ort_stadt': 'München',
      'buchung.reiseanlass': 'besuch_niederlassung',
      'buchung.besuch_niederlassung': 'München',
    }
    // innerhalb der Richtlinie → vollständig
    expect(validatePhaseCompletion(DEFN, start,
      { ...base, 'buchung.budget_bestaetigung': 'unter_120' })).toEqual([])

    // Abweichung → Begründung und Genehmigung werden Pflicht
    const errs = validatePhaseCompletion(DEFN, start,
      { ...base, 'buchung.budget_bestaetigung': 'abweichung' })
    expect(errs.map((e) => e.path).sort())
      .toEqual(['buchung.budget_begruendung', 'buchung.budget_genehmigung'])
  })
})
