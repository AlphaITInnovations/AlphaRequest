import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import {
  advance, canSeeField, currentApproval, currentPhase, enterStatusFor, filterValues,
  initialRuntime, isTerminal,
  renderFields, resolveResponsibility, responsibilityText, sendBack, simAdvance, simDecide,
  simSetValues, startSim, validatePhaseCompletion,
  validateValues, visibleFieldKeys,
} from './processSim'
import type { SimViewer } from './processSim'

const DEFN = normalizeDefinition({
  key: 'demo', name: 'Demo',
  fields: [
    { key: 'base.name', widget: 'text', constraints: { maxLength: 5 } },
    { key: 'base.age', widget: 'number', constraints: { min: 18 } },
    { key: 'fuhrpark.car', widget: 'select', options: [{ value: 'Ja' }, { value: 'Nein' }] },
    { key: 'fuhrpark.plate', widget: 'text' },
    { key: 'it.host', widget: 'text', visibility: { confidential: false, visibleToGroups: ['g_it'] } },
    { key: 'personal.salary', widget: 'text', visibility: { confidential: true, visibleToGroups: ['g_hr'] } },
    { key: 'salary_copy', widget: 'text', computed: { from: 'personal.salary' } },
  ],
  phases: [
    { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [
        { ref: 'base.name', required: true },
        { ref: 'fuhrpark.car' },
        { ref: 'fuhrpark.plate', visibleWhen: { '==': ['fuhrpark.car', 'Ja'] },
          requiredWhen: { '==': ['fuhrpark.car', 'Ja'] } },
      ],
      constraints: [{ when: { truthy: 'base.name' }, message: 'Name nötig' }] },
    { key: 'review', kind: 'review',
      responsibility: { kind: 'departments', rule: [
        { group: 'g_it' }, { group: 'g_fp', when: { '==': ['fuhrpark.car', 'Ja'] } }] },
      fields: [{ ref: 'base.name', mode: 'readonly' }, { ref: 'it.host', mode: 'editable' }] },
  ],
})

const ADMIN: SimViewer = { fullView: true, isAdmin: true, groupIds: [] }
const FULL: SimViewer = { fullView: true, isAdmin: false, groupIds: [] }
const IT: SimViewer = { fullView: false, isAdmin: false, groupIds: ['g_it'] }
const HR: SimViewer = { fullView: false, isAdmin: false, groupIds: ['g_hr'] }
const OUT: SimViewer = { fullView: false, isAdmin: false, groupIds: [] }

const field = (k: string) => DEFN.fields.find((f) => f.key === k)!

describe('Sichtbarkeit (Spiegel des Servers)', () => {
  it('geteilte Felder sehen alle', () => {
    for (const v of [ADMIN, FULL, IT, HR, OUT]) expect(canSeeField(field('base.name'), v)).toBe(true)
  })

  it('gruppen-beschränkte Felder: Gruppe oder Vollsicht', () => {
    expect(canSeeField(field('it.host'), IT)).toBe(true)
    expect(canSeeField(field('it.host'), FULL)).toBe(true)
    expect(canSeeField(field('it.host'), OUT)).toBe(false)
  })

  it('vertraulich ist ein HARTES Gate – Vollsicht reicht nicht', () => {
    expect(canSeeField(field('personal.salary'), FULL)).toBe(false)
    expect(canSeeField(field('personal.salary'), HR)).toBe(true)
    expect(canSeeField(field('personal.salary'), ADMIN)).toBe(true)
    expect(canSeeField(field('personal.salary'), IT)).toBe(false)
  })

  it('ein berechnetes Spiegelfeld erbt die Sichtbarkeit seiner Quelle', () => {
    // Regression: sonst liefe ein vertraulicher Wert über die Kopie ab.
    const keys = visibleFieldKeys(DEFN, FULL)
    expect(keys.has('personal.salary')).toBe(false)
    expect(keys.has('salary_copy')).toBe(false)
    expect(visibleFieldKeys(DEFN, HR).has('salary_copy')).toBe(true)
  })

  it('filterValues gibt nur Sichtbares zurück', () => {
    const values = { 'base.name': 'Max', 'it.host': 'PC-1', 'personal.salary': '50k' }
    expect(filterValues(DEFN, values, IT)).toEqual({ 'base.name': 'Max', 'it.host': 'PC-1' })
    expect(filterValues(DEFN, values, OUT)).toEqual({ 'base.name': 'Max' })
    expect(filterValues(DEFN, values, ADMIN)).toEqual(values)
  })
})

describe('renderFields', () => {
  it('blendet Felder aus, deren visibleWhen nicht erfüllt ist', () => {
    const off = renderFields(DEFN, DEFN.phases[0], { 'fuhrpark.car': 'Nein' }, ADMIN)
    expect(off.find((r) => r.ref.ref === 'fuhrpark.plate')!.visible).toBe(false)
    const on = renderFields(DEFN, DEFN.phases[0], { 'fuhrpark.car': 'Ja' }, ADMIN)
    const plate = on.find((r) => r.ref.ref === 'fuhrpark.plate')!
    expect(plate.visible).toBe(true)
    expect(plate.required).toBe(true)     // requiredWhen greift ebenfalls
  })

  it('markiert readonly-Felder als nicht bearbeitbar', () => {
    const r = renderFields(DEFN, DEFN.phases[1], {}, ADMIN)
    expect(r.find((x) => x.ref.ref === 'base.name')!.editable).toBe(false)
    expect(r.find((x) => x.ref.ref === 'it.host')!.editable).toBe(true)
  })

  it('unsichtbare Felder sind nie pflicht', () => {
    const r = renderFields(DEFN, DEFN.phases[1], {}, OUT)
    expect(r.find((x) => x.ref.ref === 'it.host')!.visible).toBe(false)
    expect(r.find((x) => x.ref.ref === 'it.host')!.required).toBe(false)
  })
})

describe('Validierung', () => {
  it('Pass 1 prüft Typ, Optionen und Constraints', () => {
    expect(validateValues(DEFN, { 'kein.feld': 1 })[0].code).toBe('UNKNOWN_FIELD')
    expect(validateValues(DEFN, { 'base.age': 'zwölf' })[0].code).toBe('TYPE')
    expect(validateValues(DEFN, { 'base.age': 12 })[0].code).toBe('MIN')
    expect(validateValues(DEFN, { 'base.name': 'zulang' })[0].code).toBe('MAX_LENGTH')
    expect(validateValues(DEFN, { 'fuhrpark.car': 'Vielleicht' })[0].code).toBe('OPTION')
    expect(validateValues(DEFN, { 'base.name': 'Max', 'base.age': 30 })).toEqual([])
  })

  it('Pass 2 prüft Pflicht, bedingte Pflicht und Regeln', () => {
    const missing = validatePhaseCompletion(DEFN, DEFN.phases[0], { 'fuhrpark.car': 'Ja' })
    expect(missing.map((e) => e.path)).toContain('base.name')
    expect(missing.map((e) => e.path)).toContain('fuhrpark.plate')
    const ok = validatePhaseCompletion(DEFN, DEFN.phases[0],
      { 'base.name': 'Max', 'fuhrpark.car': 'Nein' })
    expect(ok).toEqual([])
  })
})

describe('Laufzeit', () => {
  it('startet in der ersten Phase', () => {
    const rt = initialRuntime(DEFN, 't0')
    expect(rt.current_index).toBe(0)
    expect(rt.phases[0].status).toBe('open')
    expect(rt.phases[1].status).toBe('pending')
  })

  it('leitet den Status aus der Phasen-Art ab', () => {
    expect(enterStatusFor(DEFN.phases[0])).toBe('in_progress')
    expect(enterStatusFor(DEFN.phases[1])).toBe('in_request')
  })

  it('schaltet weiter und archiviert am Ende', () => {
    let rt = initialRuntime(DEFN, 't0')
    let res = advance(DEFN, rt, 't1')
    expect(res.status).toBe('in_request')
    expect(currentPhase(DEFN, res.runtime)!.key).toBe('review')
    res = advance(DEFN, res.runtime, 't2')
    expect(res.status).toBe('archived')
    expect(isTerminal(DEFN, res.runtime)).toBe(true)
  })

  it('löst bedingte Fachabteilungen auf', () => {
    const withCar = resolveResponsibility(DEFN.phases[1], { 'fuhrpark.car': 'Ja' })
    expect(withCar.departments!.map((d) => d.group).sort()).toEqual(['g_fp', 'g_it'])
    const without = resolveResponsibility(DEFN.phases[1], { 'fuhrpark.car': 'Nein' })
    expect(without.departments!.map((d) => d.group)).toEqual(['g_it'])
  })
})

describe('Simulation', () => {
  it('blockiert den Abschluss bei fehlenden Pflichtangaben', () => {
    const s = startSim(DEFN, 't0')
    const res = simAdvance(DEFN, s, 't1')
    expect(res.errors.length).toBeGreaterThan(0)
    expect(res.state.runtime.current_index).toBe(0)   // unverändert
  })

  it('läuft mit gültigen Werten bis zum Ende durch', () => {
    let s = startSim(DEFN, 't0')
    s = simSetValues(DEFN, s, { 'base.name': 'Max', 'fuhrpark.car': 'Nein' })
    const first = simAdvance(DEFN, s, 't1')
    expect(first.errors).toEqual([])
    expect(currentPhase(DEFN, first.state.runtime)!.key).toBe('review')
    const second = simAdvance(DEFN, first.state, 't2')
    expect(second.state.status).toBe('archived')
    expect(second.state.events.length).toBeGreaterThanOrEqual(3)
  })

  it('füllt berechnete Felder beim Setzen', () => {
    let s = startSim(DEFN, 't0')
    s = simSetValues(DEFN, s, { 'personal.salary': '50k' })
    expect(s.values['salary_copy']).toBe('50k')
  })
})

// ── Zuständigkeit aus einem Feld ─────────────────────────────────────────────

const AUS_FELD = normalizeDefinition({
  key: 'demo2', name: 'Demo 2',
  fields: [
    { key: 'abteilung', widget: 'group' },
    { key: 'verantwortlich', widget: 'user' },
  ],
  phases: [
    { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
      fields: [{ ref: 'abteilung' }, { ref: 'verantwortlich' }] },
    { key: 'fach', kind: 'task',
      responsibility: { kind: 'group_from_field', fromField: 'abteilung' } },
    { key: 'person', kind: 'task',
      responsibility: { kind: 'assignable', fromField: 'verantwortlich' } },
  ],
})

describe('Zuständigkeit aus einem Feld', () => {
  it('löst group_from_field zu einer Gruppen-Zuständigkeit auf', () => {
    const res = resolveResponsibility(AUS_FELD.phases[1], { abteilung: 'g_it' })
    expect(res).toMatchObject({ kind: 'group', group: 'g_it', fromField: 'abteilung' })
  })

  it('löst assignable zu einer Personen-Zuständigkeit auf', () => {
    const res = resolveResponsibility(AUS_FELD.phases[2], { verantwortlich: 'u1' })
    expect(res).toMatchObject({ kind: 'user', user: 'u1' })
  })

  it('nennt ein leeres Quellfeld ehrlich „noch niemand"', () => {
    const leer = resolveResponsibility(AUS_FELD.phases[1], {})
    expect(leer.group).toBeNull()
    expect(responsibilityText(leer, (id) => id)).toContain('noch niemand')
    const gefuellt = resolveResponsibility(AUS_FELD.phases[1], { abteilung: 'g_it' })
    expect(responsibilityText(gefuellt, (id) => (id === 'g_it' ? 'IT' : id))).toBe('IT')
  })

  it('beschriftet die übrigen Arten unverändert', () => {
    expect(responsibilityText(resolveResponsibility(AUS_FELD.phases[0], {}), (id) => id))
      .toBe('Ersteller:in')
    expect(responsibilityText(resolveResponsibility(DEFN.phases[1], { 'fuhrpark.car': 'Nein' }),
      (id) => id)).toBe('g_it')
  })
})

// ── Freigabe-Phase ───────────────────────────────────────────────────────────

/** Start → Freigabe. `over` verändert nur den Freigabe-Block. */
function freigabeDefn(over: Record<string, unknown> = {}) {
  return normalizeDefinition({
    key: 'demo3', name: 'Demo 3',
    fields: [{ key: 'antrag', widget: 'text' }, { key: 'entscheidung', widget: 'text' },
      { key: 'grund', widget: 'textarea' }],
    phases: [
      { key: 'erstellung', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'antrag', required: true }] },
      { key: 'freigabe', kind: 'approval', view: 'approval',
        responsibility: { kind: 'user', user: 'chef' },
        approval: { question: 'Freigeben?', ...over } },
    ],
  })
}

function beiDerFreigabe(defn: ReturnType<typeof freigabeDefn>) {
  let s = startSim(defn, 't0')
  s = simSetValues(defn, s, { antrag: 'Bitte freigeben' })
  const res = simAdvance(defn, s, 't1')
  expect(res.errors).toEqual([])
  return res.state
}

describe('Freigabe-Phase', () => {
  it('erkennt, dass in dieser Phase entschieden wird', () => {
    const defn = freigabeDefn()
    const s = beiDerFreigabe(defn)
    expect(currentApproval(defn, s)?.question).toBe('Freigeben?')
    expect(currentApproval(defn, startSim(defn, 't0'))).toBeNull()
  })

  it('schaltet bei „Ja" weiter und archiviert', () => {
    const defn = freigabeDefn()
    const res = simDecide(defn, beiDerFreigabe(defn), 'approve', {}, 't2')
    expect(res.errors).toEqual([])
    expect(res.state.status).toBe('archived')
  })

  it('verlangt bei „Nein" eine Begründung, wenn eingestellt', () => {
    const defn = freigabeDefn()
    const ohne = simDecide(defn, beiDerFreigabe(defn), 'reject', {}, 't2')
    expect(ohne.errors[0].code).toBe('REASON_REQUIRED')
    expect(ohne.state.status).not.toBe('rejected')
    const mit = simDecide(defn, beiDerFreigabe(defn), 'reject', { reason: 'Zu teuer' }, 't2')
    expect(mit.errors).toEqual([])
    expect(mit.state.status).toBe('rejected')
  })

  it('schreibt Entscheidung und Begründung in die konfigurierten Felder', () => {
    const defn = freigabeDefn({ decisionField: 'entscheidung', reasonField: 'grund' })
    const res = simDecide(defn, beiDerFreigabe(defn), 'reject', { reason: 'Zu teuer' }, 't2')
    // Gespeichert wird der ROHE Aktionsname, nicht die Beschriftung.
    expect(res.state.values.entscheidung).toBe('reject')
    expect(res.state.values.grund).toBe('Zu teuer')
  })

  it('gibt bei „Nein" mit back_to zur Nachbesserung zurück statt abzulehnen', () => {
    const defn = freigabeDefn({ onReject: 'back_to:erstellung', requireReason: false })
    const res = simDecide(defn, beiDerFreigabe(defn), 'reject', {}, 't2')
    expect(res.errors).toEqual([])
    expect(res.state.runtime.rejected).toBe(false)
    expect(currentPhase(defn, res.state.runtime)!.key).toBe('erstellung')
    // Der Epoch trägt den Durchlauf: ohne Bump blieben Fristen stumm und alte
    // Mail-Links gültig.
    expect(res.state.runtime.epoch).toBe(1)
    expect(res.state.runtime.phases[1].status).toBe('pending')
  })

  it('lehnt eine Entscheidung in einer Nicht-Freigabe-Phase ab', () => {
    const defn = freigabeDefn()
    const res = simDecide(defn, startSim(defn, 't0'), 'approve', {}, 't1')
    expect(res.errors[0].code).toBe('NO_APPROVAL')
  })

  it('schreibt bei einem gescheiterten „Ja" nichts fest', () => {
    // Freigabe-Phase mit eigener Pflichtangabe: bleibt die Phase stehen, darf
    // weder die Entscheidung im Feld noch der Verlaufseintrag zurückbleiben.
    const defn = normalizeDefinition({
      key: 'demo4', name: 'Demo 4',
      fields: [{ key: 'pflicht', widget: 'text' }, { key: 'entscheidung', widget: 'text' }],
      phases: [
        { key: 'erstellung', kind: 'start', responsibility: { kind: 'owner' } },
        { key: 'freigabe', kind: 'approval', view: 'approval',
          responsibility: { kind: 'owner' },
          fields: [{ ref: 'pflicht', required: true }],
          approval: { question: 'Ja?', decisionField: 'entscheidung' } },
      ],
    })
    const vorher = simAdvance(defn, startSim(defn, 't0'), 't1').state
    const res = simDecide(defn, vorher, 'approve', {}, 't2')
    expect(res.errors.map((e) => e.code)).toContain('REQUIRED')
    expect(res.state.values.entscheidung).toBeUndefined()
    expect(res.state.events).toEqual(vorher.events)
  })
})

describe('sendBack', () => {
  it('verweigert einen Sprung nach vorn oder auf sich selbst', () => {
    const defn = freigabeDefn()
    const s = beiDerFreigabe(defn)
    expect(sendBack(defn, s.runtime, 't2', 'freigabe')).toBeNull()
    expect(sendBack(defn, s.runtime, 't2', 'gibtsnicht')).toBeNull()
  })
})
