import { describe, it, expect } from 'vitest'
import { applyPrefill } from './processPrefill'
import type { FieldDef } from '@/types/process'

function field(key: string, prefill: { source: string; field: string } | null): FieldDef {
  return {
    key, label: null, widget: 'text', help: null, placeholder: null, options: [],
    optionsSource: null, allowOther: false, valueShape: null, constraints: null,
    visibility: null, computed: null, overridable: false, assign: null, mode: null,
    item: [], directusSource: null, directusFieldMap: [], prefill,
  } as FieldDef
}

const profile = {
  email: 'a@b.de', phone: '+49',
  employee: { last_name: 'Popp', first_name: 'Helmut', location: { name: 'Nürnberg' } },
}

describe('applyPrefill', () => {
  it('füllt aus employee/user, dot-Pfad für Relationen, überschreibt vorhandene Werte', () => {
    const fields = [
      field('nach', { source: 'employee', field: 'last_name' }),
      field('vor', { source: 'employee', field: 'first_name' }),
      field('mail', { source: 'user', field: 'email' }),
      field('nl', { source: 'employee', field: 'location.name' }),
      field('frei', null),
    ]
    const out = applyPrefill(fields, profile, { frei: 'x', nach: 'alt' })
    expect(out.nach).toBe('Popp')     // überschreibt 'alt' (read-only/autoritativ)
    expect(out.vor).toBe('Helmut')
    expect(out.mail).toBe('a@b.de')   // source=user
    expect(out.nl).toBe('Nürnberg')   // dot-Pfad über Relation
    expect(out.frei).toBe('x')        // unangetastet
  })

  it('lässt leere/fehlende Quelle unangetastet; ohne Profil kein Absturz', () => {
    const fields = [field('vor', { source: 'employee', field: 'first_name' })]
    expect(applyPrefill(fields, null, { vor: 'da' }).vor).toBe('da')
    expect(applyPrefill(fields, { employee: {} }, {}).vor).toBeUndefined()
  })

  it('löst eine Relation (Objekt/Liste) auf den Anzeigenamen auf statt [object Object]', () => {
    const fields = [field('kst', { source: 'employee', field: 'cost_center' })]
    expect(applyPrefill(fields, { employee: { cost_center: { id: '7', name: 'IT, EDV' } } }, {}).kst)
      .toBe('IT, EDV')
    expect(applyPrefill(fields, { employee: { cost_center: [{ name: 'IT' }, { name: 'EDV' }] } }, {}).kst)
      .toBe('IT, EDV')
    // Objekt ohne Anzeigefeld -> nicht gesetzt
    expect(applyPrefill(fields, { employee: { cost_center: { foo: 'bar' } } }, {}).kst).toBeUndefined()
  })
})
