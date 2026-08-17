/**
 * Beschriftung der Verlaufs-Einträge.
 *
 * Wichtig sind zwei Dinge: dass Feld-/Gruppen-/Phasen-Schlüssel als LESBARE
 * Namen erscheinen, und dass der Hinweis auf ausgeblendete Felder nicht
 * verschluckt wird – sonst sähe ein redigierter Eintrag vollständig aus.
 */
import { describe, expect, it } from 'vitest'
import type { ProcessEvent } from '@/api/processEvents'
import {
  absoluteTime, eventSummary, eventTone, relativeTime,
} from '@/lib/processEventLabels'

function ev(part: Partial<ProcessEvent> = {}): ProcessEvent {
  return {
    id: 1, action: 'updated', phase_key: 'start', epoch: 0,
    actor_id: 'u1', actor_name: 'Max', actor_type: 'user',
    internal: false, body: null, details: {}, created_at: '2026-08-10T10:00:00+00:00',
    ...part,
  }
}

const ctx = {
  fieldLabels: { 'base.name': 'Nachname', gehalt: 'Gehalt' },
  phaseLabels: { start: 'Erfassung', pruefung: 'Prüfung' },
  groupName: (id: string) => (id === 'g_it' ? 'IT-Abteilung' : id),
}

describe('eventSummary', () => {
  it('nennt geänderte Felder mit ihrer Beschriftung', () => {
    const s = eventSummary(ev({ details: { fields: ['base.name'] } }), ctx)
    expect(s).toBe('Angaben geändert: Nachname')
  })

  it('verschweigt ausgeblendete Felder nicht', () => {
    const s = eventSummary(ev({ details: { fields: ['base.name'], fields_hidden: 2 } }), ctx)
    expect(s).toContain('Nachname')
    expect(s).toContain('+2 nicht sichtbar')
  })

  it('fällt bei unbekanntem Feld auf den Schlüssel zurück', () => {
    expect(eventSummary(ev({ details: { fields: ['x.y'] } }), ctx))
      .toBe('Angaben geändert: x.y')
  })

  it('beschreibt den Phasenwechsel mit beiden Phasen', () => {
    const s = eventSummary(ev({
      action: 'advanced', details: { from_phase: 'start', to_phase: 'pruefung' },
    }), ctx)
    expect(s).toBe('Phase „Erfassung“ abgeschlossen → „Prüfung“')
  })

  it('erkennt den Abschluss des Auftrags (keine Folgephase)', () => {
    const s = eventSummary(ev({
      action: 'advanced', details: { from_phase: 'pruefung', to_phase: null },
    }), ctx)
    expect(s).toContain('Auftrag fertig')
  })

  it('unterscheidet internen und offenen Nachtrag', () => {
    expect(eventSummary(ev({ action: 'comment' }), ctx)).toBe('Nachtrag')
    expect(eventSummary(ev({ action: 'comment', internal: true }), ctx))
      .toBe('Interner Nachtrag')
  })

  it('nennt die Fachabteilung mit Namen, nicht mit ID', () => {
    expect(eventSummary(ev({ action: 'department_done', details: { group: 'g_it' } }), ctx))
      .toBe('Fachabteilung abgeschlossen: IT-Abteilung')
  })

  it('beschreibt Automationen mit Art', () => {
    const s = eventSummary(ev({
      action: 'automation_fired', details: { automation: 'eskalation7', action: 'escalate' },
    }), ctx)
    expect(s).toContain('eskalation7')
    expect(s).toContain('Eskalation')
  })

  it('bevorzugt den Anlass-Text (template) der Automation', () => {
    const s = eventSummary(ev({
      action: 'automation_fired',
      details: { automation: 'weitergabe_melden', action: 'notify',
                 template: 'Neue Aufgabe für Ihre Fachabteilung' },
    }), ctx)
    expect(s).toContain('weitergabe_melden')
    expect(s).toContain('Neue Aufgabe für Ihre Fachabteilung')
    expect(s).not.toContain('Erinnerung')
  })

  it('nennt notify ohne template „Benachrichtigung", nie „Erinnerung"', () => {
    // Alt-Einträge tragen kein template – auch dort ist „Erinnerung" für eine
    // womöglich erstmalige Mail eine Falschaussage.
    const s = eventSummary(ev({
      action: 'automation_fired', details: { automation: 'a1', action: 'notify' },
    }), ctx)
    expect(s).toContain('Benachrichtigung')
    expect(s).not.toContain('Erinnerung')
  })

  it('nennt bei der Wiederaufnahme die Phase', () => {
    expect(eventSummary(ev({ action: 'reopened', details: { phase: 'pruefung' } }), ctx))
      .toContain('Prüfung')
  })

  it('zeigt eine unbekannte Aktion als Rohwert statt sie zu verschweigen', () => {
    expect(eventSummary(ev({ action: 'irgendwas_neues' }), ctx)).toBe('irgendwas_neues')
  })

  it('stürzt bei kaputten details nicht ab', () => {
    expect(eventSummary(ev({ details: { fields: 'kein array' } as never }), ctx))
      .toBe('Angaben geändert: —')
    expect(eventSummary(ev({ action: 'department_done', details: {} }), ctx))
      .toBe('Fachabteilung abgeschlossen: —')
  })
})

describe('eventTone', () => {
  it('ordnet Ablehnungen als Gefahr ein', () => {
    expect(eventTone(ev({ action: 'rejected' }))).toBe('danger')
    expect(eventTone(ev({ action: 'department_rejected' }))).toBe('danger')
  })

  it('ordnet Wiederaufnahme und Automationen als Warnung ein', () => {
    expect(eventTone(ev({ action: 'reopened' }))).toBe('warn')
    expect(eventTone(ev({ action: 'automation_fired' }))).toBe('warn')
  })

  it('hebt Nachträge eigen hervor', () => {
    expect(eventTone(ev({ action: 'comment' }))).toBe('comment')
  })
})

describe('relativeTime', () => {
  const now = new Date('2026-08-10T12:00:00+00:00')

  it('rechnet UTC-Zeitstempel korrekt (kein Lokalzeit-Versatz)', () => {
    // Der Server liefert offset-behaftete ISO-Strings – ohne das läge die
    // Anzeige um den UTC-Versatz daneben.
    expect(relativeTime('2026-08-10T11:30:00+00:00', now)).toBe('vor 30 Min.')
    expect(relativeTime('2026-08-10T09:00:00+00:00', now)).toBe('vor 3 Std.')
  })

  it('nennt frische Einträge „gerade eben“', () => {
    expect(relativeTime('2026-08-10T11:59:30+00:00', now)).toBe('gerade eben')
  })

  it('bleibt bei fehlendem oder kaputtem Wert leer', () => {
    expect(relativeTime(null, now)).toBe('')
    expect(relativeTime('kein datum', now)).toBe('')
    expect(absoluteTime(null)).toBe('')
  })
})
