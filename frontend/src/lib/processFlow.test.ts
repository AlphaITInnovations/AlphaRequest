import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import { buildFlowModel, TERMINAL_ARCHIVED, TERMINAL_REJECTED } from './processFlow'

function defn(phases: any[]) {
  return normalizeDefinition({ key: 'k', name: 'N', phases })
}
const edge = (m: ReturnType<typeof buildFlowModel>, from: string, to: string) =>
  m.edges.find((e) => e.from === from && e.to === to)

describe('buildFlowModel', () => {
  it('verkettet lineare Phasen und endet im Terminal „archiviert"', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' } },
      { key: 'arbeit', kind: 'task', responsibility: { kind: 'owner' } },
      { key: 'ende', kind: 'end', responsibility: { kind: 'owner' } },
    ]))
    expect(m.nodes.map((n) => n.id)).toEqual(['start', 'arbeit', 'ende'])
    expect(edge(m, 'start', 'arbeit')?.kind).toBe('advance')
    expect(edge(m, 'arbeit', 'ende')?.kind).toBe('advance')
    expect(edge(m, 'ende', TERMINAL_ARCHIVED)?.kind).toBe('advance')
    expect(m.hasArchived).toBe(true)
    expect(m.hasRejected).toBe(false)
  })

  it('Freigabe mit onReject=reject → approve-Kante + reject-Kante ins Terminal', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' } },
      { key: 'freigabe', kind: 'approval', responsibility: { kind: 'group', group: 'g1' },
        approval: { question: 'OK?', onReject: 'reject', approveLabel: 'Ja', rejectLabel: 'Nein' } },
    ]))
    expect(edge(m, 'freigabe', TERMINAL_ARCHIVED)?.kind).toBe('approve')
    const rej = edge(m, 'freigabe', TERMINAL_REJECTED)
    expect(rej?.kind).toBe('reject')
    expect(rej?.label).toBe('Nein')
    expect(m.hasRejected).toBe(true)
  })

  it('Freigabe mit onReject=back_to:X → Rücksprung-Kante auf frühere Phase', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' } },
      { key: 'arbeit', kind: 'task', responsibility: { kind: 'owner' } },
      { key: 'freigabe', kind: 'approval', responsibility: { kind: 'group', group: 'g1' },
        approval: { question: 'OK?', onReject: 'back_to:arbeit' } },
    ]))
    expect(edge(m, 'freigabe', TERMINAL_ARCHIVED)?.kind).toBe('approve')
    expect(edge(m, 'freigabe', 'arbeit')?.kind).toBe('send_back')
    expect(m.hasRejected).toBe(false)   // kein Terminal „Abgelehnt", wenn zurückgesprungen wird
  })

  it('on_enter + auto_advance → Pass-Through-Knoten mit auto-Kante', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        automations: [{ trigger: { type: 'on_enter' }, action: { type: 'auto_advance' }, guard: null }] },
      { key: 'arbeit', kind: 'task', responsibility: { kind: 'owner' } },
    ]))
    const start = m.nodes.find((n) => n.id === 'start')!
    expect(start.auto).toBe(true)
    expect(start.autoConditional).toBe(false)
    expect(edge(m, 'start', 'arbeit')?.kind).toBe('auto')
  })

  it('auto_advance mit guard → bedingter Übersprung', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        automations: [{ trigger: { type: 'on_enter' }, action: { type: 'auto_advance' },
          guard: { '==': ['x', 'Ja'] } }] },
      { key: 'arbeit', kind: 'task', responsibility: { kind: 'owner' } },
    ]))
    const start = m.nodes.find((n) => n.id === 'start')!
    expect(start.autoConditional).toBe(true)
    expect(edge(m, 'start', 'arbeit')?.conditional).toBe(true)
  })

  it('review(departments) → EIN Knoten mit mehreren Lanes; bedingte Abteilung markiert', () => {
    const m = buildFlowModel(defn([
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' } },
      { key: 'pruef', kind: 'review', responsibility: { kind: 'departments', rule: [
        { group: 'g1' },
        { group: 'g2', required: false, when: { '==': ['fuhrpark.car', 'Ja'] } },
      ] } },
    ]))
    const node = m.nodes.find((n) => n.id === 'pruef')!
    expect(node.departments.map((d) => d.group)).toEqual(['g1', 'g2'])
    expect(node.departments[0]).toMatchObject({ required: true, conditional: false })
    expect(node.departments[1]).toMatchObject({ required: false, conditional: true })
  })
})
