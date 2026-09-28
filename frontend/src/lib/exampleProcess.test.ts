import { describe, it, expect } from 'vitest'
import example from '../../../docs/prozesse/onboarding-mitarbeitende.json'
import { normalizeDefinition } from './processNormalize'
import { errorCount, validateDefinition } from './processValidate'

/**
 * Die gepflegte Beispiel-Definition (docs/prozesse/) soll durch die Frontend-
 * Pipeline (Normalize + Validate) fehlerfrei durchlaufen. Ändert sich das Format
 * oder eine Whitelist, schlägt dieser Test fehl – statt dass jemand erst beim
 * Import in einen 422 läuft. (Der frühere Beispiel-Seed lag unter backend/seeds/;
 * die mitgelieferten Fach-Seeds wurden entfernt, gepflegt wird jetzt docs/prozesse/.)
 */
const DEFN = normalizeDefinition(example)

describe('Beispiel-Prozess (docs/prozesse/onboarding-mitarbeitende)', () => {
  it('ist ohne Fehler gültig', () => {
    expect(errorCount(validateDefinition(DEFN))).toBe(0)
  })

  it('hat die erwarteten Phasen', () => {
    expect(DEFN.phases.map((p) => p.key)).toEqual(
      ['erstellung', 'freigabe', 'bearbeitung', 'arbeitsvertrag', 'vertragsruecklauf', 'durchfuehrung'])
  })
})
