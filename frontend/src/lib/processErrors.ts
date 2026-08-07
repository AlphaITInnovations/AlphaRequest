/**
 * Auswertung des vereinheitlichten Fehler-Envelopes
 * { error: { code, message, fields?: [{path, code, message}] } }.
 *
 * Pydantic-Pfade kommen als 'phases.0.fields.2.ref' (nach Abzug des führenden
 * body-Markers). Daraus bauen wir DOM-Anker, damit die Oberfläche zur
 * fehlerhaften Stelle springen kann.
 */
import type { ProcessIssue } from '@/types/process'

export interface ApiErrorBody {
  code: string
  message: string
  fields?: { path: string; code: string; message: string }[]
}

export function errorBody(e: any): ApiErrorBody | null {
  const b = e?.response?.data?.error
  return b && typeof b === 'object' ? b : null
}

export function errorCode(e: any): string | null {
  return errorBody(e)?.code ?? null
}

export function errorMessage(e: any, fallback = 'Es ist ein Fehler aufgetreten'): string {
  return errorBody(e)?.message || e?.response?.data?.detail || e?.message || fallback
}

/** Anker-ID aus einem Pfad: 'phases.0.fields.2.ref' → 'pe-phase-0-field-2'. */
export function anchorForPath(path: string): string {
  const m = /^phases\.(\d+)(?:\.fields\.(\d+))?/.exec(path)
  if (m) return m[2] !== undefined ? `pe-phase-${m[1]}-field-${m[2]}` : `pe-phase-${m[1]}`
  const f = /^fields\.(\d+)/.exec(path)
  if (f) return `pe-catalog-${f[1]}`
  const a = /^automations\.(\d+)/.exec(path)
  if (a) return `pe-automation-${a[1]}`
  return 'pe-top'
}

/** Server-Feldfehler → Issues (gleiche Darstellung wie Client-Prüfungen). */
export function issuesFromError(e: any): ProcessIssue[] {
  const body = errorBody(e)
  if (!body) return []
  if (!body.fields?.length) {
    return [{ path: 'body', anchor: 'pe-top', code: body.code, severity: 'error',
      message: body.message, source: 'server' }]
  }
  return body.fields.map((f) => ({
    path: f.path,
    anchor: anchorForPath(f.path),
    code: f.code,
    severity: 'error' as const,
    message: f.message,
    source: 'server' as const,
  }))
}
