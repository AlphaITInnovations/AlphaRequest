import { describe, it, expect } from 'vitest'
import { normalizeField } from './processNormalize'
import { collectDirectusIds, mergeDirectusLabels } from './processHistoryLabels'
import type { OptionSources } from '@/types/process'

const fieldByKey = {
  'b.nl': normalizeField({ key: 'b.nl', widget: 'directus', directusSource: 'niederlassung' }),
  'b.kst': normalizeField({ key: 'b.kst', widget: 'directus', directusSource: 'kostenstelle' }),
  'b.skills': normalizeField({
    key: 'b.skills', widget: 'directus_multi', directusSource: 'skills' }),
  'b.name': normalizeField({ key: 'b.name', widget: 'text' }),
}

describe('collectDirectusIds', () => {
  it('sammelt alte UND neue IDs je Quelle, auch aus Listen (directus_multi)', () => {
    const events = [
      { action: 'updated', details: { changes: {
        'b.nl': { from: '10', to: '20' },
        'b.kst': { from: '8080', to: '8081' },
        'b.skills': { from: ['1', '2'], to: ['2', '3'] },
        'b.name': { from: 'Alt', to: 'Neu' },   // kein directus -> ignoriert
      } } },
    ]
    const out = collectDirectusIds(events, fieldByKey)
    expect(out.niederlassung.sort()).toEqual(['10', '20'])
    expect(out.kostenstelle.sort()).toEqual(['8080', '8081'])
    expect(out.skills.sort()).toEqual(['1', '2', '3'])
    expect('b.name' in out).toBe(false)
  })

  it('ignoriert nicht-„updated"-Einträge und leere Werte', () => {
    const events = [
      { action: 'created', details: { changes: { 'b.nl': { from: '10', to: '20' } } } },
      { action: 'updated', details: { changes: { 'b.nl': { from: '', to: '20' } } } },
    ]
    expect(collectDirectusIds(events, fieldByKey)).toEqual({ niederlassung: ['20'] })
  })
})

describe('mergeDirectusLabels', () => {
  const base: OptionSources = {
    users: [], groups: [], companies: [],
    directusLabels: { niederlassung: { '20': 'Nürnberg (aktuell)' } },
  } as unknown as OptionSources

  it('gibt base unverändert zurück, wenn keine Verlaufs-Labels da sind', () => {
    expect(mergeDirectusLabels(base, {})).toBe(base)
  })

  it('mischt Verlaufs-Labels dazu; die aktuellen (base) gewinnen bei Kollision', () => {
    const merged = mergeDirectusLabels(base, {
      niederlassung: { '10': 'Fürth (alt)', '20': 'Nürnberg (alt)' },
    })
    expect(merged?.directusLabels?.niederlassung).toEqual({
      '10': 'Fürth (alt)',            // aus dem Verlauf ergänzt
      '20': 'Nürnberg (aktuell)',     // base gewinnt
    })
  })

  it('funktioniert auch ohne base', () => {
    const merged = mergeDirectusLabels(undefined, { kostenstelle: { '8080': 'KST 8080' } })
    expect(merged?.directusLabels?.kostenstelle).toEqual({ '8080': 'KST 8080' })
  })
})
