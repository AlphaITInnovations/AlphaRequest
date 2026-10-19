import { describe, it, expect } from 'vitest'
import { buildReviewChangeMap, mergeEpochChanges } from './processReviewChanges'
import type { ProcessEvent } from '@/api/processEvents'
import type { FieldDef } from '@/types/process'

const field = (key: string, prefill = false): FieldDef => ({
  key, widget: 'text', label: key,
  prefill: prefill ? { source: 'employee', field: key } : null,
} as unknown as FieldDef)

const FIELDS: Record<string, FieldDef> = {
  'stammdaten.mobile': field('stammdaten.mobile', true),
  'stammdaten.private_mail': field('stammdaten.private_mail', true),
  'stammdaten.private_phone': field('stammdaten.private_phone', true),
  'onboarding.titel': field('onboarding.titel', false),
}

const ev = (epoch: number, changes: Record<string, { from: unknown; to: unknown }>,
            action = 'updated'): ProcessEvent => ({
  id: Math.random(), action, phase_key: null, epoch, actor_id: null, actor_name: null,
  actor_type: 'user', internal: false, body: null, details: { changes }, created_at: null,
})

describe('buildReviewChangeMap', () => {
  it('geändert: alt → neu', () => {
    const m = buildReviewChangeMap({ 'stammdaten.mobile': { from: '0151', to: '0170' } }, FIELDS)
    expect(m['stammdaten.mobile']).toEqual(
      { fromText: '0151', toText: '0170', fromEmpty: false, toEmpty: false })
  })

  it('Regression: vorher leer, jetzt befüllt → bei Vorbelegung sichtbar (Stammdaten)', () => {
    const m = buildReviewChangeMap({ 'stammdaten.private_mail': { from: null, to: 'neu@privat.de' } }, FIELDS)
    expect(m['stammdaten.private_mail']).toMatchObject({ toText: 'neu@privat.de', fromEmpty: true })
  })

  it('Regression: entfernt (alt → leer) ist sichtbar', () => {
    const m = buildReviewChangeMap({ 'stammdaten.private_phone': { from: '0911-123', to: null } }, FIELDS)
    expect(m['stammdaten.private_phone']).toMatchObject({ fromText: '0911-123', toEmpty: true })
  })

  it('reine Erst-Eingabe OHNE Vorbelegung bleibt unmarkiert (Onboarding)', () => {
    expect(buildReviewChangeMap({ 'onboarding.titel': { from: null, to: 'IT' } }, FIELDS)).toEqual({})
  })

  it('keine Änderung: gleich, oder leer ↔ leer, oder unbekanntes Feld', () => {
    expect(buildReviewChangeMap({
      'stammdaten.mobile': { from: '0170', to: '0170' },
      'stammdaten.private_mail': { from: null, to: '' },
      'gibtsnicht': { from: 'a', to: 'b' },
    }, FIELDS)).toEqual({})
  })
})

describe('mergeEpochChanges', () => {
  it('ältester „from", jüngster „to"; nur der aktuelle Durchlauf, nur „updated"', () => {
    const merged = mergeEpochChanges([
      ev(0, { 'stammdaten.mobile': { from: 'x', to: 'y' } }),                 // alter Durchlauf
      ev(1, { 'stammdaten.mobile': { from: '0151', to: '0160' } }),
      ev(1, { 'stammdaten.mobile': { from: '0160', to: '0170' } }),
      ev(1, { 'stammdaten.private_mail': { from: null, to: 'a@b' } }, 'comment'),
    ], 1)
    expect(merged).toEqual({ 'stammdaten.mobile': { from: '0151', to: '0170' } })
  })
})
