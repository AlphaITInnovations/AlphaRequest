import { describe, it, expect } from 'vitest'
import {
  ACTION_TYPES, PHASE_KINDS, PHASE_VIEWS, RESPONSIBILITY_KINDS, WIDGETS_TOP,
  backToTarget, blankApproval, blankAssign, blankPhase, blankResponsibility,
  isValidOnReject, phaseKindPatch, responsibilityKindPatch,
} from './processSchema'

/**
 * Die Whitelists sind der Spiegel des Meta-Schemas. Bietet der Editor etwas an,
 * das der Server ablehnt, sieht das niemand vor dem Speichern-Fehler – und
 * umgekehrt verschweigt er sonst Möglichkeiten.
 */
describe('Whitelists', () => {
  it('kennt die freigeschalteten Werte', () => {
    expect(PHASE_KINDS).toContain('approval')
    expect(PHASE_VIEWS).toContain('approval')
    expect(PHASE_VIEWS).toContain('export')
    expect(WIDGETS_TOP).toContain('server_generated')
    expect(ACTION_TYPES).toContain('assign_sequence')
    expect(RESPONSIBILITY_KINDS).toContain('group_from_field')
  })

  it('bietet die gestrichenen Werte nicht mehr an', () => {
    expect(RESPONSIBILITY_KINDS as readonly string[]).not.toContain('originator')
    expect(ACTION_TYPES as readonly string[]).not.toContain('spawn_process')
    expect(ACTION_TYPES as readonly string[]).not.toContain('require_attachment')
  })

  it('lässt server_stamped nur in Unterfeldern zu', () => {
    expect(WIDGETS_TOP).not.toContain('server_stamped')
  })
})

describe('onReject', () => {
  it('erkennt die beiden erlaubten Formen', () => {
    expect(isValidOnReject('reject')).toBe(true)
    expect(isValidOnReject('back_to:erstellung')).toBe(true)
    expect(isValidOnReject('back_to:Mit-Strich')).toBe(false)   // Phasen-Alphabet
    expect(isValidOnReject('vielleicht')).toBe(false)
    expect(isValidOnReject('')).toBe(false)
  })

  it('liefert das Rücksprung-Ziel', () => {
    expect(backToTarget('back_to:erstellung')).toBe('erstellung')
    expect(backToTarget('reject')).toBeNull()
  })
})

describe('Leer-Vorlagen', () => {
  it('legt eine Freigabe-Phase komplett an', () => {
    const p = blankPhase('freigabe', 'approval')
    expect(p.view).toBe('approval')
    expect(p.approval).toEqual(blankApproval())
  })

  it('lässt approval bei jeder anderen Phasen-Art leer', () => {
    expect(blankPhase('arbeit', 'task').approval).toBeNull()
    expect(blankPhase('pruefung', 'review').approval).toBeNull()
  })

  it('setzt die einzig erlaubte Vergabe-Aktion', () => {
    expect(blankAssign().action).toBe('assign_sequence')
    expect(blankAssign().counter).toBeTruthy()
  })
})

describe('phaseKindPatch', () => {
  it('richtet beim Wechsel auf „Freigabe" Block und Ansicht ein', () => {
    const p = blankPhase('x', 'task')
    const patch = phaseKindPatch(p, 'approval')
    expect(patch.approval).toEqual(blankApproval())
    expect(patch.view).toBe('approval')
  })

  it('behält eine bereits erfasste Freigabe', () => {
    const p = { ...blankPhase('x', 'approval'), approval: blankApproval('Schon getippt?') }
    // Umweg über eine andere Art und zurück: der Text darf nicht überschrieben
    // werden, solange er im Objekt steht.
    expect(phaseKindPatch(p, 'approval').approval?.question).toBe('Schon getippt?')
  })

  it('räumt Block und Ansicht beim Wechsel weg von „Freigabe" ab', () => {
    const p = blankPhase('x', 'approval')
    const patch = phaseKindPatch(p, 'task')
    expect(patch.approval).toBeNull()
    expect(patch.view).toBe('form')
  })

  it('lässt eine unbeteiligte Ansicht in Ruhe', () => {
    const p = { ...blankPhase('x', 'task'), view: 'readonly' as const }
    expect(phaseKindPatch(p, 'end').view).toBe('readonly')
  })
})

describe('responsibilityKindPatch', () => {
  it('verwirft das Quellfeld beim Wechsel zwischen den Feld-Arten', () => {
    // Ein Personen-Feld taugt nicht als Fachabteilung – der Server lehnt das ab.
    const cur = { ...blankResponsibility('assignable'), fromField: 'verantwortlich' }
    expect(responsibilityKindPatch(cur, 'group_from_field').fromField).toBeNull()
  })

  it('behält das Quellfeld, wenn die Art gleich bleibt', () => {
    const cur = { ...blankResponsibility('assignable'), fromField: 'verantwortlich' }
    expect(responsibilityKindPatch(cur, 'assignable').fromField).toBe('verantwortlich')
  })

  it('räumt Gruppe, Person und Abteilungsliste auf', () => {
    const cur = { ...blankResponsibility('group'), group: 'g_it', user: 'u1' }
    const next = responsibilityKindPatch(cur, 'owner')
    expect(next.group).toBeNull()
    expect(next.user).toBeNull()
    expect(next.rule).toEqual([])
  })

  it('legt für „Mehrere Fachabteilungen" eine erste Zeile an', () => {
    const next = responsibilityKindPatch(blankResponsibility('owner'), 'departments')
    expect(next.rule.length).toBe(1)
    expect(next.rule[0].required).toBe(true)
  })
})
