import { describe, it, expect } from 'vitest'
import {
  isSafeInternalPath, rememberPostLoginPath, takePostLoginPath, POST_LOGIN_MAX_AGE_MS,
} from './postLoginRedirect'

function memStorage() {
  const m = new Map<string, string>()
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, v) },
    removeItem: (k: string) => { m.delete(k) },
    raw: m,
  }
}

describe('isSafeInternalPath', () => {
  it('interne Pfade inkl. Query sind erlaubt', () => {
    expect(isSafeInternalPath('/prozess-auftraege/42?ansicht=bearbeiten')).toBe(true)
    expect(isSafeInternalPath('/prozesse/loeschen?token=abc')).toBe(true)
  })
  it('keine Fremd-URLs (protokoll-relativ, absolut)', () => {
    expect(isSafeInternalPath('//evil.example/x')).toBe(false)
    expect(isSafeInternalPath('/\\evil.example')).toBe(false)
    expect(isSafeInternalPath('https://evil.example')).toBe(false)
    expect(isSafeInternalPath('javascript:alert(1)')).toBe(false)
  })
  it('keine Login-/Fehlerseiten', () => {
    for (const p of ['/login', '/login?error=x', '/logout', '/start-auth', '/auth/callback',
                     '/backend-down', '/kein-zugang']) {
      expect(isSafeInternalPath(p)).toBe(false)
    }
  })
  it('kein String / zu lang', () => {
    expect(isSafeInternalPath(null)).toBe(false)
    expect(isSafeInternalPath(42)).toBe(false)
    expect(isSafeInternalPath('/' + 'a'.repeat(3000))).toBe(false)
  })
})

describe('remember/take', () => {
  const T = 1_800_000_000_000

  it('merkt und löst genau einmal ein', () => {
    const s = memStorage()
    rememberPostLoginPath('/prozess-auftraege/42?ansicht=bearbeiten', T, s)
    expect(takePostLoginPath(T + 60_000, s)).toBe('/prozess-auftraege/42?ansicht=bearbeiten')
    expect(takePostLoginPath(T + 61_000, s)).toBeNull()
  })

  it('zu alt → vergessen (abgebrochener Login)', () => {
    const s = memStorage()
    rememberPostLoginPath('/archiv', T, s)
    expect(takePostLoginPath(T + POST_LOGIN_MAX_AGE_MS + 1, s)).toBeNull()
  })

  it('unsichere Pfade werden weder gemerkt noch eingelöst', () => {
    const s = memStorage()
    rememberPostLoginPath('//evil.example', T, s)
    expect(s.raw.size).toBe(0)
    s.setItem('postLoginPath', JSON.stringify({ path: '//evil.example', at: T }))
    expect(takePostLoginPath(T, s)).toBeNull()
  })

  it('kaputter Speicherinhalt / kein Speicher → null', () => {
    const s = memStorage()
    s.setItem('postLoginPath', 'kein json')
    expect(takePostLoginPath(T, s)).toBeNull()
    expect(takePostLoginPath(T, null)).toBeNull()
  })
})
