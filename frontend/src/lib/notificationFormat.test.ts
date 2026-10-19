import { describe, it, expect } from 'vitest'
import { badgeText, bellLabel, kindMeta } from './notificationFormat'

describe('notificationFormat', () => {
  it('Plakette deckelt bei 99+', () => {
    expect(badgeText(0)).toBe('0')
    expect(badgeText(7)).toBe('7')
    expect(badgeText(99)).toBe('99')
    expect(badgeText(100)).toBe('99+')
  })

  it('Knopf-Beschriftung nennt die Ungelesenen', () => {
    expect(bellLabel(0)).toBe('Benachrichtigungen')
    expect(bellLabel(3)).toBe('Benachrichtigungen (3 ungelesen)')
  })

  it('Art → Beschriftung, unbekannte Art fällt neutral zurück', () => {
    expect(kindMeta('task').label).toBe('Neue Aufgabe')
    expect(kindMeta('gibtsnicht').label).toBe('Hinweis')
  })
})
