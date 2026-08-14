/**
 * System-Prozesse in der Oberfläche.
 *
 * Zwei Dinge müssen stimmen, sonst ist der Schutz löchrig oder lästig:
 * das Merkmal darf NICHT geraten werden (sonst verschwinden Knöpfe an einem
 * änderbaren Prozess), und die Ablehnung des Servers muss erkannt werden – sie
 * ist der eigentliche Schutz.
 */
import { describe, it, expect } from 'vitest'
import type { ProcessIssue } from '@/types/process'
import {
  SYSTEM_PROCESS_READONLY, hasSystemReadonlyIssue, isSystemProcess, isSystemReadonlyError,
} from './processSystem'

/** Fehler, wie ihn axios für den Envelope { error: { code, message } } liefert. */
function apiError(code: string) {
  return { response: { data: { error: { code, message: 'nicht änderbar' } } } }
}

function issue(code: string): ProcessIssue {
  return { path: 'body', anchor: 'pe-top', code, severity: 'error', message: 'x', source: 'server' }
}

describe('isSystemProcess', () => {
  it('folgt allein dem Merkmal des Servers', () => {
    expect(isSystemProcess({ is_system: true })).toBe(true)
    expect(isSystemProcess({ is_system: false })).toBe(false)
  })

  it('rät nicht anhand des Schlüssels', () => {
    // Ein älteres Backend schickt das Merkmal nicht mit: dann bleiben die Knöpfe
    // sichtbar und der Server weist notfalls ab. Eine Schlüssel-Liste hier würde
    // irgendwann veralten und Knöpfe an änderbaren Prozessen ausblenden.
    expect(isSystemProcess({ key: 'basis-ticket' } as never)).toBe(false)
    expect(isSystemProcess({})).toBe(false)
    expect(isSystemProcess(null)).toBe(false)
    expect(isSystemProcess(undefined)).toBe(false)
  })
})

describe('isSystemReadonlyError', () => {
  it('erkennt die Ablehnung des Servers', () => {
    expect(isSystemReadonlyError(apiError(SYSTEM_PROCESS_READONLY))).toBe(true)
  })

  it('verwechselt sie mit keinem anderen Fehler', () => {
    expect(isSystemReadonlyError(apiError('PROCESS_VERSION_IN_USE'))).toBe(false)
    expect(isSystemReadonlyError(new Error('Netz weg'))).toBe(false)
    expect(isSystemReadonlyError(null)).toBe(false)
  })

  it('hält den Code fest, mit dem das Backend antwortet', () => {
    expect(SYSTEM_PROCESS_READONLY).toBe('SYSTEM_PROCESS_READONLY')
  })
})

describe('hasSystemReadonlyIssue', () => {
  it('findet die Ablehnung in der Issue-Liste des Editors', () => {
    expect(hasSystemReadonlyIssue([issue('PROCESS_INVALID'), issue(SYSTEM_PROCESS_READONLY)])).toBe(true)
  })

  it('meldet nichts ohne passenden Code', () => {
    expect(hasSystemReadonlyIssue([])).toBe(false)
    expect(hasSystemReadonlyIssue([issue('PROCESS_VERSION_CONFLICT')])).toBe(false)
  })
})
