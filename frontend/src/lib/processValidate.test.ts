import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import { dslRefs, errorCount, isWellFormedCondition, validateDefinition } from './processValidate'

function defn(over: Record<string, unknown> = {}) {
  return normalizeDefinition({
    key: 'demo', name: 'Demo',
    fields: [{ key: 'base.name', widget: 'text' }, { key: 'fuhrpark.car', widget: 'select',
      options: [{ value: 'Ja' }, { value: 'Nein' }] }],
    phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'base.name', required: true }] }],
    ...over,
  })
}

const codes = (d: ReturnType<typeof defn>) => validateDefinition(d).map((i) => i.code)

describe('validateDefinition – Grundgerüst', () => {
  it('meldet nichts bei einer gültigen Definition', () => {
    expect(errorCount(validateDefinition(defn()))).toBe(0)
  })

  it('verlangt genau eine Start-Phase, und zwar zuerst', () => {
    const d1 = defn({ phases: [{ key: 'a', kind: 'task', responsibility: { kind: 'owner' } }] })
    expect(codes(d1)).toContain('MISSING_START')
    const d2 = defn({ phases: [
      { key: 'a', kind: 'task', responsibility: { kind: 'owner' } },
      { key: 'b', kind: 'start', responsibility: { kind: 'owner' } },
    ] })
    expect(codes(d2)).toContain('START_NOT_FIRST')
  })

  it('erkennt doppelte Schlüssel', () => {
    const d = defn({ fields: [{ key: 'a', widget: 'text' }, { key: 'a', widget: 'text' }] })
    expect(codes(d)).toContain('DUPLICATE_KEY')
  })

  it('prüft die drei Schlüssel-Alphabete', () => {
    expect(codes(defn({ key: 'Groß_Falsch' }))).toContain('INVALID_KEY')
    expect(codes(defn({ phases: [{ key: 'mit-strich', kind: 'start',
      responsibility: { kind: 'owner' } }] }))).toContain('INVALID_KEY')
    expect(codes(defn({ fields: [{ key: 'mit-strich', widget: 'text' }] }))).toContain('INVALID_KEY')
  })
})

describe('validateDefinition – Referenzen', () => {
  it('meldet unbekannte fieldRefs', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'gibt.es.nicht' }] }] })
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('meldet unbekannte Referenzen in Bedingungen', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'base.name', requiredWhen: { '==': ['tippfehler', 'Ja'] } }] }] })
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('meldet computed.from auf ein unbekanntes Feld', () => {
    const d = defn({ fields: [{ key: 'a', widget: 'text', computed: { from: 'weg' } }] })
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('verbietet berechnete, nicht überschreibbare Felder als bearbeitbar', () => {
    const d = defn({
      fields: [{ key: 'src', widget: 'text' },
        { key: 'calc', widget: 'text', computed: { from: 'src' }, overridable: false }],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'calc', mode: 'editable' }] }],
    })
    expect(codes(d)).toContain('COMPUTED_NOT_EDITABLE')
  })
})

describe('validateDefinition – serverseitig abgelehnte Werte', () => {
  it('lehnt terminale enterStatus ab', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      enterStatus: 'archived' }] })
    expect(codes(d)).toContain('UNSUPPORTED')
  })

  it('lehnt nicht implementierte Phasen-Arten ab', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' } },
      { key: 'frei', kind: 'approval', responsibility: { kind: 'owner' } }] })
    expect(codes(d)).toContain('UNSUPPORTED')
  })

  it('lehnt nicht implementierte Aktionen ab', () => {
    const d = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' },
      action: { type: 'spawn_process', process: 'y' } }] })
    expect(codes(d)).toContain('UNSUPPORTED')
  })

  it('prüft Empfänger-Ziele', () => {
    const bad = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' },
      action: { type: 'notify', to: 'tippfehler' } }] })
    expect(codes(bad)).toContain('INVALID')
    const ok = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' },
      action: { type: 'notify', to: 'group:abc' } }] })
    expect(errorCount(validateDefinition(ok))).toBe(0)
  })

  it('prüft ISO-Dauern der Timer', () => {
    const bad = defn({ automations: [{ id: 'x', trigger: { type: 'timer', after: 'P1M' },
      action: { type: 'notify', to: 'owner' } }] })
    expect(codes(bad)).toContain('INVALID')
    const ok = defn({ automations: [{ id: 'x', trigger: { type: 'timer', after: 'P7D', repeat: 'P7D' },
      action: { type: 'notify', to: 'owner' } }] })
    expect(errorCount(validateDefinition(ok))).toBe(0)
  })

  it('verlangt Gruppen bei vertraulichen Feldern', () => {
    const d = defn({ fields: [{ key: 'gehalt', widget: 'text',
      visibility: { confidential: true, visibleToGroups: [] } }] })
    expect(codes(d)).toContain('REQUIRED')
  })

  it('erkennt doppelte Automations-IDs', () => {
    const d = defn({
      automations: [{ id: 'dup', trigger: { type: 'on_enter' }, action: { type: 'notify', to: 'owner' } }],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        automations: [{ id: 'dup', trigger: { type: 'on_enter' }, action: { type: 'notify', to: 'owner' } }] }],
    })
    expect(codes(d)).toContain('DUPLICATE_KEY')
  })
})

describe('validateDefinition – Warnungen', () => {
  it('warnt bei unbekannten Gruppen, blockiert aber nicht', () => {
    // base.name muss im Katalog bleiben – die Start-Phase referenziert es.
    const d = defn({ fields: [
      { key: 'base.name', widget: 'text' },
      { key: 'g', widget: 'text', visibility: { confidential: true, visibleToGroups: ['weg'] } },
    ] })
    const issues = validateDefinition(d, new Set(['bekannt']))
    expect(issues.some((i) => i.code === 'UNKNOWN_GROUP' && i.severity === 'warning')).toBe(true)
    expect(errorCount(issues)).toBe(0)
  })
})

describe('validateDefinition – Layout', () => {
  const withLayout = (layout: unknown[]) => defn({
    fields: [{ key: 'a', widget: 'text' }, { key: 'b', widget: 'text' }],
    phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'a' }, { ref: 'b' }], layout }],
  })

  it('akzeptiert ein saubere Layout', () => {
    const d = withLayout([{ type: 'section', title: 'Person', variant: 'hr', items: [
      { type: 'field', ref: 'a', width: 'half' },
      { type: 'note', text: 'Hinweis', tone: 'info' },
      { type: 'field', ref: 'b', width: 'half' },
    ] }])
    expect(errorCount(validateDefinition(d))).toBe(0)
  })

  it('meldet ein Feld, das nicht zur Phase gehört', () => {
    const d = withLayout([{ type: 'section', items: [{ type: 'field', ref: 'fremd' }] }])
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('meldet doppelt platzierte Felder', () => {
    const d = withLayout([{ type: 'section', items: [
      { type: 'field', ref: 'a' }, { type: 'field', ref: 'a' }] }])
    expect(codes(d)).toContain('DUPLICATE_REF')
  })

  it('warnt bei nicht platzierten Feldern, blockiert aber nicht', () => {
    const d = withLayout([{ type: 'section', items: [{ type: 'field', ref: 'a' }] }])
    const issues = validateDefinition(d)
    expect(issues.some((x) => x.code === 'UNPLACED' && x.severity === 'warning')).toBe(true)
    expect(errorCount(issues)).toBe(0)
  })

  it('warnt bei leeren Design-Elementen', () => {
    const d = withLayout([{ type: 'section', items: [
      { type: 'field', ref: 'a' }, { type: 'field', ref: 'b' },
      { type: 'note', text: '' }, { type: 'heading', text: '  ' }] }])
    const issues = validateDefinition(d)
    expect(issues.filter((x) => x.code === 'EMPTY').length).toBe(2)
    expect(errorCount(issues)).toBe(0)
  })

  it('ohne Layout gibt es keine Layout-Meldungen', () => {
    const d = withLayout([])
    expect(validateDefinition(d).some((x) => x.code === 'UNPLACED')).toBe(false)
  })
})

describe('DSL-Helfer', () => {
  it('sammelt Referenzen rekursiv', () => {
    expect(dslRefs({ and: [{ truthy: 'a' }, { '==': ['b', 1] }, { not: { in: ['c', [1]] } }] }).sort())
      .toEqual(['a', 'b', 'c'])
  })

  it('erkennt wohlgeformte und kaputte Ausdrücke', () => {
    expect(isWellFormedCondition({ truthy: 'a' })).toBe(true)
    expect(isWellFormedCondition({ and: [{ truthy: 'a' }] })).toBe(true)
    expect(isWellFormedCondition({ '==': ['a'] })).toBe(false)
    expect(isWellFormedCondition({ in: ['a', 'keineliste'] })).toBe(false)
    expect(isWellFormedCondition({ and: [] })).toBe(false)
    expect(isWellFormedCondition({ unbekannt: 1 })).toBe(false)
    expect(isWellFormedCondition({ '==': ['a', 1], or: [] })).toBe(false)
  })
})
