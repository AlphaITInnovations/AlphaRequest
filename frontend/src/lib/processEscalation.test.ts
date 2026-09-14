import { describe, it, expect } from 'vitest'
import { normalizeDefinition, canonicalJson } from './processNormalize'
import { validateDefinition, errorCount } from './processValidate'
import {
  blankEscalation, blankEscalationStage, isValidRecipient, phaseKindPatch, ESCALATION_MAX_DAYS,
} from './processSchema'
import { normalizePhase } from './processNormalize'

/** Prozess mit einer Bearbeitungs-Phase, die den escalation-Block trägt. */
function defn(escalation: unknown, kind = 'task') {
  return normalizeDefinition({
    key: 'demo', name: 'Demo',
    fields: [{ key: 'base.name', widget: 'text' }],
    phases: [
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'base.name' }] },
      { key: 'bearbeitung', kind, responsibility: { kind: 'group', group: 'g_it' },
        escalation },
      { key: 'ende', kind: 'end', responsibility: { kind: 'owner' } },
    ],
  })
}
const codes = (d: ReturnType<typeof defn>, users?: Set<string>) =>
  validateDefinition(d, new Set(['g_it']), users).map((i) => i.code)

// ── Empfänger-Token ───────────────────────────────────────────────────────────

describe('isValidRecipient', () => {
  it('akzeptiert Rollen und ID-Ziele, lehnt Unfug ab', () => {
    for (const ok of ['responsible', 'owner', 'watchers', 'group:g1', 'user:u1']) {
      expect(isValidRecipient(ok)).toBe(true)
    }
    for (const bad of ['', 'supervisor', 'group:', 'user:', 'chef']) {
      expect(isValidRecipient(bad)).toBe(false)
    }
  })
})

// ── Normalisierung / Dirty-Stabilität ─────────────────────────────────────────

describe('normEscalation', () => {
  it('fehlender Block bleibt null (kein Phantom-Dirty)', () => {
    const d = normalizeDefinition({
      key: 'k', name: 'N', fields: [{ key: 'a', widget: 'text' }],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' } }],
    })
    expect(d.phases[0].escalation).toBeNull()
  })

  it('blankEscalation ist bereits normalisiert (stabiler Vergleich)', () => {
    const blank = blankEscalation()
    const round = normalizeDefinition(defn(blank)).phases[1].escalation
    expect(canonicalJson(round)).toBe(canonicalJson(blank))
  })

  it('füllt alle Stufen-Keys und ist idempotent', () => {
    const raw = { enabled: true, stages: [
      { afterDays: 7, repeatDays: 7, recipients: ['responsible', 'user:u1'] }] }
    const once = normalizeDefinition(defn(raw))
    const twice = normalizeDefinition(once)
    expect(canonicalJson(once)).toBe(canonicalJson(twice))
    const st = once.phases[1].escalation!.stages[0]
    expect(st).toEqual({ afterDays: 7, repeatDays: 7,
      recipients: ['responsible', 'user:u1'], message: null, raisePriority: false })
  })

  it('behält recipients an einer Automation-Action', () => {
    const d = normalizeDefinition({
      key: 'k', name: 'N', fields: [{ key: 'a', widget: 'text' }],
      phases: [{ key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        automations: [{ id: 'x', trigger: { type: 'timer', after: 'P7D' },
          action: { type: 'notify', recipients: ['responsible', 'user:u1'] } }] }],
    })
    expect(d.phases[0].automations[0].action.recipients).toEqual(['responsible', 'user:u1'])
  })
})

// ── Validierung ───────────────────────────────────────────────────────────────

describe('validateDefinition – Eskalation', () => {
  it('gültige Eskalation meldet keinen Fehler', () => {
    const d = defn({ enabled: true, stages: [
      { afterDays: 7, repeatDays: 7, recipients: ['responsible', 'group:g_it'] },
      { afterDays: 14, recipients: ['owner'], raisePriority: true },
    ] })
    expect(errorCount(validateDefinition(d, new Set(['g_it'])))).toBe(0)
  })

  it('leere Empfänger → REQUIRED', () => {
    expect(codes(defn({ enabled: true, stages: [{ afterDays: 7, recipients: [] }] })))
      .toContain('REQUIRED')
  })

  it('afterDays 0 und repeatDays 0 → INVALID', () => {
    expect(codes(defn({ enabled: true, stages: [{ afterDays: 0, recipients: ['owner'] }] })))
      .toContain('INVALID')
    expect(codes(defn({ enabled: true,
      stages: [{ afterDays: 7, repeatDays: 0, recipients: ['owner'] }] })))
      .toContain('INVALID')
  })

  it('unbekanntes Empfänger-Token → INVALID', () => {
    expect(codes(defn({ enabled: true,
      stages: [{ afterDays: 7, recipients: ['supervisor'] }] })))
      .toContain('INVALID')
  })

  it('aktiv ohne Stufen → REQUIRED', () => {
    expect(codes(defn({ enabled: true, stages: [] }))).toContain('REQUIRED')
  })

  it('deaktiviert ohne Stufen ist ok', () => {
    expect(errorCount(validateDefinition(defn({ enabled: false, stages: [] }),
      new Set(['g_it'])))).toBe(0)
  })

  it('Eskalation an einer Abschluss-Phase → INVALID', () => {
    // Block direkt an der end-Phase (dritte Phase)
    const d = normalizeDefinition({
      key: 'k', name: 'N', fields: [{ key: 'a', widget: 'text' }],
      phases: [
        { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
          fields: [{ ref: 'a' }] },
        { key: 'ende', kind: 'end', responsibility: { kind: 'owner' },
          escalation: { enabled: true, stages: [{ afterDays: 7, recipients: ['owner'] }] } },
      ],
    })
    expect(validateDefinition(d).map((i) => i.code)).toContain('INVALID')
  })

  it('unbekannte Empfänger-Person → Warnung, bekannte nicht', () => {
    const stage = { afterDays: 7, recipients: ['user:weg'] }
    const warnUnknown = validateDefinition(defn({ enabled: true, stages: [stage] }),
      new Set(['g_it']), new Set(['u1']))
    expect(warnUnknown.some((i) => i.code === 'UNKNOWN_USER')).toBe(true)

    const known = validateDefinition(
      defn({ enabled: true, stages: [{ afterDays: 7, recipients: ['user:u1'] }] }),
      new Set(['g_it']), new Set(['u1']))
    expect(known.some((i) => i.code === 'UNKNOWN_USER')).toBe(false)
  })

  it('afterDays/repeatDays über der Obergrenze → INVALID (Spiegel der Server-Grenze)', () => {
    expect(codes(defn({ enabled: true,
      stages: [{ afterDays: ESCALATION_MAX_DAYS + 1, recipients: ['owner'] }] })))
      .toContain('INVALID')
    expect(codes(defn({ enabled: true,
      stages: [{ afterDays: 7, repeatDays: ESCALATION_MAX_DAYS + 1, recipients: ['owner'] }] })))
      .toContain('INVALID')
    // exakt an der Grenze ist ok
    expect(errorCount(validateDefinition(defn({ enabled: true,
      stages: [{ afterDays: ESCALATION_MAX_DAYS, recipients: ['owner'] }] }), new Set(['g_it']))))
      .toBe(0)
  })

  it('blankEscalationStage hat noch keine Empfänger (blockt bis zur Auswahl)', () => {
    const st = blankEscalationStage()
    expect(st.recipients).toEqual([])
    expect(st.afterDays).toBe(7)
  })
})

describe('phaseKindPatch – Eskalation', () => {
  it('entfernt escalation beim Wechsel auf eine Abschluss-Phase', () => {
    const ph = normalizePhase({ key: 'b', kind: 'task', responsibility: { kind: 'owner' },
      escalation: { enabled: true, stages: [{ afterDays: 7, recipients: ['owner'] }] } })
    expect(phaseKindPatch(ph, 'end').escalation).toBeNull()
  })

  it('behält escalation bei einem Wechsel unter Nicht-End-Arten', () => {
    const ph = normalizePhase({ key: 'b', kind: 'task', responsibility: { kind: 'owner' },
      escalation: { enabled: true, stages: [{ afterDays: 7, recipients: ['owner'] }] } })
    expect(phaseKindPatch(ph, 'review').escalation).toEqual(ph.escalation)
  })
})
