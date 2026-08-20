import { describe, it, expect } from 'vitest'
import {
  canonicalJson, cloneDefinition, isSameDefinition, normalizeDefinition, normalizeField,
  normalizeFieldRef,
} from './processNormalize'

describe('normalizeDefinition', () => {
  it('füllt fehlende Keys auf und ist idempotent', () => {
    const once = normalizeDefinition({ key: 'k', name: 'N' })
    const twice = normalizeDefinition(once)
    expect(canonicalJson(once)).toBe(canonicalJson(twice))
    expect(once.fields).toEqual([])
    expect(once.phases).toEqual([])
    expect(once.description).toBeNull()
    expect(once.schemaVersion).toBe(1)
  })

  it('akzeptiert from_ und gibt immer from aus (Python-Alias)', () => {
    const f = normalizeField({ key: 'a', widget: 'text', computed: { from_: 'b' } })
    expect(f.computed).toEqual({ from: 'b', map: null })
    const g = normalizeField({ key: 'a', widget: 'text', computed: { from: 'c' } })
    expect(g.computed).toEqual({ from: 'c', map: null })
    // Lookup-Map wird durchgereicht
    const h = normalizeField({ key: 'a', widget: 'text', computed: { from: 'p', map: { X: 'Y' } } })
    expect(h.computed).toEqual({ from: 'p', map: { X: 'Y' } })
  })

  it('kennt die gegensätzlichen required-Defaults', () => {
    // FieldRef.required → false
    expect(normalizeFieldRef({ ref: 'a' }).required).toBe(false)
    // DepartmentRule.required → true
    const d = normalizeDefinition({
      key: 'k', name: 'N',
      phases: [{ key: 'p', kind: 'review', responsibility: { kind: 'departments', rule: [{ group: 'g' }] } }],
    })
    expect(d.phases[0].responsibility.rule[0].required).toBe(true)
  })

  it('behält Extra-Keys in Phasen-Regeln (Server verbietet sie dort nicht)', () => {
    const d = normalizeDefinition({
      key: 'k', name: 'N',
      phases: [{ key: 'p', kind: 'start', responsibility: { kind: 'owner' },
        constraints: [{ when: { truthy: 'a' }, message: 'm', extra: 42 }] }],
    })
    expect((d.phases[0].constraints[0] as any).extra).toBe(42)
  })

  it('normalisiert String-Optionen zu {value,label}', () => {
    const f = normalizeField({ key: 'a', widget: 'select', options: ['Ja', { value: 'Nein', label: 'Nein!' }] })
    expect(f.options).toEqual([{ value: 'Ja', label: null }, { value: 'Nein', label: 'Nein!' }])
  })

  it('erfindet keinen Freigabe-Block, wo keiner steht', () => {
    // Sonst wäre jede Nicht-Freigabe-Phase serverseitig ungültig UND der Entwurf
    // sofort „geändert".
    const d = normalizeDefinition({ key: 'k', name: 'N',
      phases: [{ key: 'p', kind: 'task', responsibility: { kind: 'owner' } }] })
    expect(d.phases[0].approval).toBeNull()
  })

  it('füllt einen vorhandenen Freigabe-Block mit den Server-Defaults', () => {
    const d = normalizeDefinition({ key: 'k', name: 'N',
      phases: [{ key: 'f', kind: 'approval', responsibility: { kind: 'owner' },
        approval: { question: 'Freigeben?' } }] })
    expect(d.phases[0].approval).toEqual({
      question: 'Freigeben?', approveLabel: 'Freigeben', rejectLabel: 'Ablehnen',
      externalLink: true, emailBody: null, linkMaxAge: 'P7D', requireReason: true,
      decisionField: null, reasonField: null, onReject: 'reject',
    })
  })

  it('übernimmt abweichende Freigabe-Angaben unverändert', () => {
    const d = normalizeDefinition({ key: 'k', name: 'N',
      phases: [{ key: 'f', kind: 'approval', responsibility: { kind: 'owner' },
        approval: { question: 'Ja?', externalLink: false, requireReason: false,
          linkMaxAge: 'PT12H', onReject: 'back_to:start', reasonField: 'grund' } }] })
    const a = d.phases[0].approval!
    expect(a.externalLink).toBe(false)
    expect(a.requireReason).toBe(false)
    expect(a.linkMaxAge).toBe('PT12H')
    expect(a.onReject).toBe('back_to:start')
    expect(a.reasonField).toBe('grund')
  })

  it('serialisiert keine gestrichenen Keys (Action.process)', () => {
    // Der Server verbietet unbekannte Keys (extra="forbid") – ein mitgeschleiftes
    // `process: null` würde jede Definition unspeicherbar machen.
    const d = normalizeDefinition({ key: 'k', name: 'N',
      automations: [{ id: 'a', trigger: { type: 'on_enter' },
        action: { type: 'notify', to: 'owner', process: 'alt' } }] })
    expect(Object.keys(d.automations[0].action).sort())
      .toEqual(['counter', 'field', 'template', 'to', 'type', 'value'])
  })

  it('ergänzt die einzig erlaubte assign.action', () => {
    const f = normalizeField({ key: 'pnr', widget: 'server_generated',
      assign: { counter: 'personalnummer' } })
    expect(f.assign).toEqual({ action: 'assign_sequence', counter: 'personalnummer',
      companyRef: null })
  })
})

describe('canonicalJson', () => {
  it('ist unabhängig von der Schlüssel-Reihenfolge', () => {
    expect(canonicalJson({ a: 1, b: { c: 2, d: 3 } }))
      .toBe(canonicalJson({ b: { d: 3, c: 2 }, a: 1 }))
  })

  it('erkennt echte Unterschiede', () => {
    expect(canonicalJson({ a: 1 })).not.toBe(canonicalJson({ a: 2 }))
  })
})

describe('isSameDefinition / cloneDefinition', () => {
  it('vergleicht über die normalisierte Form', () => {
    // Server liefert alle Keys, der Editor baut nur die nötigen – trotzdem gleich.
    expect(isSameDefinition({ key: 'k', name: 'N' },
      { key: 'k', name: 'N', description: null, icon: null, fields: [], phases: [],
        automations: [], schemaVersion: 1 })).toBe(true)
  })

  it('sieht eine Freigabe-Phase vom Server als unverändert an', () => {
    // Regression Dirty-Vergleich: Server liefert ALLE Keys, der Editor baut nur
    // die nötigen. Weichen die Defaults ab, gilt jeder Entwurf sofort als geändert.
    const knapp = { key: 'k', name: 'N', phases: [{ key: 'f', kind: 'approval',
      view: 'approval', responsibility: { kind: 'owner' },
      approval: { question: 'Ja?' } }] }
    const vollstaendig = {
      schemaVersion: 1, key: 'k', name: 'N', description: null, icon: null,
      createPermissions: { everyone: false, groups: [], users: [] },
      fields: [], automations: [],
      phases: [{ key: 'f', label: null, kind: 'approval', view: 'approval',
        enterStatus: null, grantsFullView: false,
        responsibility: { kind: 'owner', group: null, user: null, fromField: null,
          rule: [], resetOnDescriptionChange: false, notifyOnEnter: true },
        approval: { question: 'Ja?', approveLabel: 'Freigeben', rejectLabel: 'Ablehnen',
          externalLink: true, linkMaxAge: 'P7D', requireReason: true,
          decisionField: null, reasonField: null, onReject: 'reject' },
        fields: [], layout: [], constraints: [], automations: [] }],
    }
    expect(isSameDefinition(knapp, vollstaendig)).toBe(true)
  })

  it('klont ohne geteilte Referenzen', () => {
    const a = normalizeDefinition({ key: 'k', name: 'N', fields: [{ key: 'f', widget: 'text' }] })
    const b = cloneDefinition(a)
    b.fields[0].key = 'geaendert'
    expect(a.fields[0].key).toBe('f')
  })
})
