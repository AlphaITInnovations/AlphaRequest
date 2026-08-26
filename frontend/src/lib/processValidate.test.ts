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

  it('lehnt gestrichene Aktionen ab (spawn_process/require_attachment)', () => {
    for (const type of ['spawn_process', 'require_attachment']) {
      const d = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' }, action: { type } }] })
      expect(codes(d)).toContain('UNSUPPORTED')
    }
  })

  it('lehnt die gestrichene Zuständigkeit „originator" ab', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start',
      responsibility: { kind: 'originator' } }] })
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

// ── Freigeschaltete Werte + ihre neuen Regeln ────────────────────────────────

const START = { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
  fields: [{ ref: 'base.name', required: true }] }

/** Prozess mit Start-Phase + einer Freigabe-Phase (Abweichungen per `over`). */
function withApproval(over: Record<string, unknown> = {}, felder?: unknown[]) {
  return defn({
    ...(felder ? { fields: felder } : {}),
    phases: [START, {
      key: 'freigabe', kind: 'approval', view: 'approval',
      responsibility: { kind: 'user', user: 'u1' },
      approval: { question: 'Wirklich freigeben?', ...over },
    }],
  })
}

describe('validateDefinition – freigeschaltete Werte', () => {
  it('akzeptiert eine vollständige Freigabe-Phase', () => {
    expect(errorCount(validateDefinition(withApproval()))).toBe(0)
  })

  it('akzeptiert die Ansicht „Export"', () => {
    const d = defn({ phases: [START, { key: 'ende', kind: 'end', view: 'export',
      responsibility: { kind: 'owner' } }] })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })

  it('akzeptiert server_generated mit assign', () => {
    const d = defn({
      fields: [{ key: 'base.name', widget: 'text' }, { key: 'firma', widget: 'company' },
        { key: 'pnr', widget: 'server_generated',
          assign: { action: 'assign_sequence', counter: 'personalnummer', companyRef: 'firma' } }],
      phases: [{ ...START, fields: [{ ref: 'base.name' }, { ref: 'pnr', mode: 'readonly' }] }],
    })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })

  it('akzeptiert die Aktion assign_sequence mit Nummernkreis und Feld', () => {
    const d = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' },
      action: { type: 'assign_sequence', counter: 'personalnummer', field: 'base.name' } }] })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })

  it('akzeptiert die Zuständigkeit „Fachabteilung aus einem Feld"', () => {
    const d = defn({
      fields: [{ key: 'base.name', widget: 'text' }, { key: 'abteilung', widget: 'group' }],
      phases: [START, { key: 'bearbeitung', kind: 'task',
        responsibility: { kind: 'group_from_field', fromField: 'abteilung' } }],
    })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })
})

describe('validateDefinition – Freigabe-Regeln', () => {
  it('verlangt den Freigabe-Block bei kind=approval', () => {
    const d = defn({ phases: [START, { key: 'freigabe', kind: 'approval', view: 'approval',
      responsibility: { kind: 'owner' } }] })
    expect(codes(d)).toContain('REQUIRED')
  })

  it('verbietet den Freigabe-Block bei jeder anderen Phasen-Art', () => {
    const d = defn({ phases: [START, { key: 'arbeit', kind: 'task',
      responsibility: { kind: 'owner' }, approval: { question: 'Ja?' } }] })
    expect(codes(d)).toContain('INVALID')
  })

  it('verbietet die Ansicht „Freigabe" ohne die passende Phasen-Art', () => {
    const d = defn({ phases: [START, { key: 'arbeit', kind: 'task', view: 'approval',
      responsibility: { kind: 'owner' } }] })
    expect(codes(d)).toContain('INVALID')
  })

  it('verlangt eine Frage', () => {
    expect(codes(withApproval({ question: '   ' }))).toContain('REQUIRED')
  })

  it('prüft die Gültigkeitsdauer des Mail-Links', () => {
    expect(codes(withApproval({ linkMaxAge: 'P1M' }))).toContain('INVALID')
    expect(errorCount(validateDefinition(withApproval({ linkMaxAge: 'PT12H' })))).toBe(0)
  })

  it('meldet ein Rücksprung-Ziel, das es nicht gibt', () => {
    expect(codes(withApproval({ onReject: 'back_to:gibtsnicht' }))).toContain('UNKNOWN_REF')
  })

  it('meldet ein Rücksprung-Ziel, das nicht VOR der Freigabe liegt', () => {
    // Sprung auf sich selbst …
    expect(codes(withApproval({ onReject: 'back_to:freigabe' }))).toContain('INVALID')
    // … und ein Sprung nach vorn.
    const d = defn({ phases: [START,
      { key: 'freigabe', kind: 'approval', view: 'approval',
        responsibility: { kind: 'owner' },
        approval: { question: 'Ja?', onReject: 'back_to:spaeter' } },
      { key: 'spaeter', kind: 'task', responsibility: { kind: 'owner' } }] })
    expect(codes(d)).toContain('INVALID')
  })

  it('akzeptiert einen Rücksprung auf eine frühere Phase', () => {
    expect(errorCount(validateDefinition(withApproval({ onReject: 'back_to:start' })))).toBe(0)
  })

  it('meldet ein unbekanntes Verhalten bei „Nein"', () => {
    expect(codes(withApproval({ onReject: 'vielleicht' }))).toContain('INVALID')
  })

  it('meldet unbekannte Entscheidungs-/Begründungs-Felder', () => {
    const d = withApproval({ decisionField: 'weg', reasonField: 'auchweg' })
    expect(validateDefinition(d).filter((i) => i.code === 'UNKNOWN_REF').length).toBe(2)
  })
})

describe('validateDefinition – Zuständigkeit aus einem Feld', () => {
  const mitFeldern = (resp: Record<string, unknown>) => defn({
    fields: [{ key: 'base.name', widget: 'text' }, { key: 'abteilung', widget: 'group' },
      { key: 'person', widget: 'user' }],
    phases: [START, { key: 'arbeit', kind: 'task', responsibility: resp }],
  })

  it('verlangt das Quellfeld', () => {
    expect(codes(mitFeldern({ kind: 'group_from_field' }))).toContain('REQUIRED')
    expect(codes(mitFeldern({ kind: 'assignable' }))).toContain('REQUIRED')
  })

  it('meldet ein Quellfeld, das es nicht gibt', () => {
    expect(codes(mitFeldern({ kind: 'group_from_field', fromField: 'weg' })))
      .toContain('UNKNOWN_REF')
  })

  it('verlangt den richtigen Feldtyp je Zuständigkeit', () => {
    // Fachabteilung aus einem PERSONEN-Feld …
    expect(codes(mitFeldern({ kind: 'group_from_field', fromField: 'person' })))
      .toContain('INVALID')
    // … und Person aus einem FACHABTEILUNGS-Feld.
    expect(codes(mitFeldern({ kind: 'assignable', fromField: 'abteilung' })))
      .toContain('INVALID')
  })
})

describe('validateDefinition – vom Server vergebene Nummern', () => {
  const mitPnr = (feld: Record<string, unknown>, phase?: Record<string, unknown>) => defn({
    fields: [{ key: 'base.name', widget: 'text' }, { key: 'firma', widget: 'company' },
      { key: 'pnr', ...feld }],
    phases: [{ ...START, fields: [{ ref: 'base.name' }, { ref: 'pnr', mode: 'readonly' },
      ...(phase ? [phase] : [])] }],
  })

  it('verlangt die Vergabe-Angaben bei server_generated', () => {
    expect(codes(mitPnr({ widget: 'server_generated' }))).toContain('REQUIRED')
  })

  it('verlangt den Nummernkreis', () => {
    expect(codes(mitPnr({ widget: 'server_generated',
      assign: { action: 'assign_sequence', companyRef: 'firma' } }))).toContain('REQUIRED')
  })

  it('lässt nur assign_sequence als Vergabe-Aktion zu', () => {
    expect(codes(mitPnr({ widget: 'server_generated',
      assign: { action: 'set_field', counter: 'personalnummer', companyRef: 'firma' } })))
      .toContain('UNSUPPORTED')
  })

  it('verbietet ein server_generated-Feld als bearbeitbar', () => {
    const d = defn({
      fields: [{ key: 'base.name', widget: 'text' }, { key: 'firma', widget: 'company' },
        { key: 'pnr', widget: 'server_generated',
          assign: { action: 'assign_sequence', counter: 'personalnummer', companyRef: 'firma' } }],
      phases: [{ ...START, fields: [{ ref: 'pnr', mode: 'editable' }] }],
    })
    expect(codes(d)).toContain('SERVER_FIELD_NOT_EDITABLE')
  })

  it('verlangt Nummernkreis UND Zielfeld bei der Aktion', () => {
    const ohneBeides = defn({ automations: [{ id: 'x', trigger: { type: 'on_enter' },
      action: { type: 'assign_sequence' } }] })
    expect(ohneBeides && validateDefinition(ohneBeides)
      .filter((i) => i.code === 'REQUIRED').length).toBe(2)
  })

  it('warnt bei unbekanntem Nummernkreis, blockiert aber nicht', () => {
    const d = mitPnr({ widget: 'server_generated',
      assign: { action: 'assign_sequence', counter: 'rechnungsnummer', companyRef: 'firma' } })
    const issues = validateDefinition(d)
    expect(issues.some((i) => i.code === 'UNKNOWN_COUNTER' && i.severity === 'warning')).toBe(true)
    expect(errorCount(issues)).toBe(0)
  })

  it('warnt, wenn die Nummer nie vergeben werden kann', () => {
    const d = defn({
      fields: [{ key: 'base.name', widget: 'text' }, { key: 'firma', widget: 'company' },
        { key: 'pnr', widget: 'server_generated',
          assign: { action: 'assign_sequence', counter: 'personalnummer', companyRef: 'firma' } }],
      phases: [START],   // keine Phase führt „pnr"
    })
    const issues = validateDefinition(d)
    expect(issues.some((i) => i.code === 'NEVER_ASSIGNED' && i.severity === 'warning')).toBe(true)
    expect(errorCount(issues)).toBe(0)
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

describe('validateDefinition – Directus-Feld', () => {
  // Zusatzfelder bearbeitbar einbinden: Auto-Fill-Ziele müssen dort beschreibbar
  // sein, wo das directus-Feld beschreibbar ist (sonst greift die Writable-Regel).
  const withField = (f: Record<string, unknown>, extra: Record<string, unknown>[] = []) =>
    defn({
      fields: [f, ...extra],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: (f as any).key }, ...extra.map((e) => ({ ref: (e as any).key }))] }],
    })

  it('verlangt eine Quelle bei widget=directus', () => {
    expect(codes(withField({ key: 'kst', widget: 'directus' }))).toContain('REQUIRED')
  })

  it('meldet unbekanntes Ziel-Feld im Mapping', () => {
    const d = withField({ key: 'kst', widget: 'directus', directusSource: 'kostenstelle',
      directusFieldMap: [{ source: 'firma.name', target: 'ghost' }] })
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('akzeptiert ein gültiges Directus-Feld mit Mapping', () => {
    const d = withField(
      { key: 'kst', widget: 'directus', directusSource: 'kostenstelle',
        directusFieldMap: [{ source: 'firma.name', target: 'firma' }] },
      [{ key: 'firma', widget: 'text' }])
    expect(errorCount(validateDefinition(d))).toBe(0)
  })

  it('lehnt Directus-Props bei anderem Feldtyp ab', () => {
    expect(codes(withField({ key: 'a', widget: 'text', directusSource: 'x' }))).toContain('INVALID')
  })

  it('erlaubt ein read-only Auto-Fill-Ziel (Snapshot schreibt der Server)', () => {
    const d = defn({
      fields: [
        { key: 'kst', widget: 'directus', directusSource: 'kostenstelle',
          directusFieldMap: [{ source: 'firma.name', target: 'firma' }] },
        { key: 'firma', widget: 'text' }],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'kst' }, { ref: 'firma', mode: 'readonly' }] }],
    })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })
})

describe('validateDefinition – directus_write & on_department_done', () => {
  it('verlangt idField im Katalog beim directus_write', () => {
    const d = defn({ phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'base.name' }],
      automations: [{ id: 'w', trigger: { type: 'on_enter' }, action: { type: 'directus_write',
        directus: { operation: 'create', collection: 'c', idField: 'ghost',
          fieldMap: [{ source: 'base.name', target: 'name' }] } } }] }] })
    expect(codes(d)).toContain('UNKNOWN_REF')
  })

  it('on_department_done nur in einer Fachabteilungs-Phase', () => {
    const d = defn({ phases: [
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' }, fields: [{ ref: 'base.name' }] },
      { key: 't', kind: 'task', responsibility: { kind: 'group', group: 'g' },
        fields: [{ ref: 'base.name', mode: 'readonly' }],
        automations: [{ id: 'x', trigger: { type: 'on_department_done', group: 'g' },
          action: { type: 'notify', to: 'responsible' } }] }] })
    expect(codes(d)).toContain('INVALID')
  })

  it('akzeptiert directus_write per on_department_done in einer review-Phase', () => {
    const d = defn({
      fields: [{ key: 'base.name', widget: 'text' }, { key: 'mid', widget: 'text' }],
      phases: [
        { key: 'start', kind: 'start', responsibility: { kind: 'owner' }, fields: [{ ref: 'base.name' }] },
        { key: 'rev', kind: 'review', view: 'review',
          responsibility: { kind: 'departments', rule: [{ group: 'g-it', required: true }] },
          fields: [{ ref: 'base.name', mode: 'readonly' }],
          automations: [{ id: 'anlegen', trigger: { type: 'on_department_done', group: 'g-it' },
            action: { type: 'directus_write', directus: { operation: 'create', collection: 'mitarbeiter',
              idField: 'mid', fieldMap: [{ source: 'base.name', target: 'name' }] } } }] }] })
    expect(errorCount(validateDefinition(d))).toBe(0)
  })
})
