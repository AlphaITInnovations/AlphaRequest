/**
 * Client-Simulation der Prozess-Laufzeit – Spiegel von
 * process_runtime.py, process_visibility.py, process_validation.py.
 *
 * Zwei Einsatzzwecke:
 *  1. Vorschau im Editor (ohne Wegwerf-Ticket, ohne API).
 *  2. Das echte Ticket-Formular: welche Felder sind sichtbar, bearbeitbar,
 *     pflicht? Der Server bleibt autoritativ – hier geht es um die Darstellung.
 */
import type {
  Condition, FieldDef, FieldRef, PhaseDef, ProcessDefinition, ProcessRuntime,
} from '@/types/process'
import { evaluate, applyComputed, isEmpty } from '@/lib/conditionDsl'

export interface SimViewer {
  fullView: boolean
  isAdmin: boolean
  groupIds: string[]
}

export const ADMIN_VIEWER: SimViewer = { fullView: true, isAdmin: true, groupIds: [] }

export interface SimFieldError { path: string; code: string; message: string }

// ── Sichtbarkeit (Spiegel process_visibility) ─────────────────────────────────

export function canSeeField(f: FieldDef, ctx: SimViewer): boolean {
  const vis = f.visibility
  const confidential = !!vis?.confidential
  const groups = vis?.visibleToGroups ?? []
  if (confidential) {
    // Hartes Gate: Vollsicht hilft NICHT – nur Gruppenmitglieder oder Admin.
    return ctx.isAdmin || groups.some((g) => ctx.groupIds.includes(g))
  }
  if (groups.length === 0) return true
  return ctx.fullView || groups.some((g) => ctx.groupIds.includes(g))
}

/** Ein berechnetes Feld ist nur sichtbar, wenn auch seine Quelle sichtbar ist. */
export function effectiveCanSee(
  f: FieldDef, ctx: SimViewer, byKey: Map<string, FieldDef>, seen = new Set<string>(),
): boolean {
  if (!canSeeField(f, ctx)) return false
  if (f.computed) {
    if (seen.has(f.key)) return true
    seen.add(f.key)
    const src = byKey.get(f.computed.from)
    if (src && !effectiveCanSee(src, ctx, byKey, seen)) return false
  }
  return true
}

export function visibleFieldKeys(defn: ProcessDefinition, ctx: SimViewer): Set<string> {
  const byKey = new Map(defn.fields.map((f) => [f.key, f]))
  return new Set(defn.fields.filter((f) => effectiveCanSee(f, ctx, byKey)).map((f) => f.key))
}

export function filterValues(
  defn: ProcessDefinition, values: Record<string, unknown>, ctx: SimViewer,
): Record<string, unknown> {
  const allowed = visibleFieldKeys(defn, ctx)
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(values)) if (allowed.has(k)) out[k] = v
  return out
}

// ── Welche Felder zeigt eine Phase? ───────────────────────────────────────────

export interface RenderedField {
  ref: FieldRef
  field: FieldDef
  visible: boolean
  required: boolean
  editable: boolean
}

/**
 * Die Felder einer Phase in Anzeige-Reihenfolge, jeweils mit ausgewerteten
 * Bedingungen. `visible=false` → nicht rendern (mode 'hidden', visibleWhen
 * nicht erfüllt oder Sichtbarkeit fehlt).
 */
export function renderFields(
  defn: ProcessDefinition, phase: PhaseDef, values: Record<string, unknown>, ctx: SimViewer,
): RenderedField[] {
  const byKey = new Map(defn.fields.map((f) => [f.key, f]))
  const out: RenderedField[] = []
  for (const ref of phase.fields) {
    const field = byKey.get(ref.ref)
    if (!field) continue
    const seeable = effectiveCanSee(field, ctx, byKey)
    const condOk = ref.visibleWhen ? evaluate(ref.visibleWhen as Condition, values) : true
    const visible = seeable && condOk && ref.mode !== 'hidden'
    const required = visible && (ref.required
      || (!!ref.requiredWhen && evaluate(ref.requiredWhen as Condition, values)))
    const editable = visible && (ref.mode === 'editable' || ref.mode === 'append_only')
    out.push({ ref, field, visible, required, editable })
  }
  return out
}

// ── Validierung (Spiegel process_validation) ──────────────────────────────────

const LIST_WIDGETS = ['multiselect', 'checkbox-group', 'collection']
const TEXTY = ['text', 'textarea', 'date', 'select', 'user', 'company', 'group']

/** Pass 1: Wert-Form der gesendeten Felder. */
export function validateValues(
  defn: ProcessDefinition, submitted: Record<string, unknown>,
): SimFieldError[] {
  const byKey = new Map(defn.fields.map((f) => [f.key, f]))
  const errs: SimFieldError[] = []
  for (const [key, val] of Object.entries(submitted)) {
    const f = byKey.get(key)
    if (!f) { errs.push({ path: key, code: 'UNKNOWN_FIELD', message: `Unbekanntes Feld „${key}"` }); continue }
    if (val === null || val === undefined) continue
    const w = f.widget
    if (w === 'number') {
      if (typeof val !== 'number' || Number.isNaN(val)) {
        errs.push({ path: key, code: 'TYPE', message: 'Zahl erwartet' }); continue
      }
    } else if (w === 'checkbox') {
      if (typeof val !== 'boolean') {
        errs.push({ path: key, code: 'TYPE', message: 'Ja/Nein erwartet' }); continue
      }
    } else if (LIST_WIDGETS.includes(w)) {
      if (!Array.isArray(val)) {
        errs.push({ path: key, code: 'TYPE', message: 'Liste erwartet' }); continue
      }
    } else if (TEXTY.includes(w)) {
      if (typeof val !== 'string') {
        errs.push({ path: key, code: 'TYPE', message: 'Text erwartet' }); continue
      }
    }
    if (f.options.length && ['select', 'multiselect', 'checkbox-group'].includes(w)) {
      const allowed = new Set(f.options.map((o) => o.value))
      const picked = Array.isArray(val) ? val : [val]
      const bad = picked.filter((p) => !allowed.has(String(p)))
      if (bad.length && !f.allowOther) {
        errs.push({ path: key, code: 'OPTION', message: `Ungültige Auswahl: ${bad.join(', ')}` })
      }
    }
    const c = f.constraints
    if (c && typeof val === 'string') {
      if (c.minLength != null && val.length < c.minLength) {
        errs.push({ path: key, code: 'MIN_LENGTH', message: `mindestens ${c.minLength} Zeichen` })
      }
      if (c.maxLength != null && val.length > c.maxLength) {
        errs.push({ path: key, code: 'MAX_LENGTH', message: `höchstens ${c.maxLength} Zeichen` })
      }
      if (c.pattern) {
        try { if (!new RegExp(`^(?:${c.pattern})$`).test(val)) {
          errs.push({ path: key, code: 'PATTERN', message: 'Format ungültig' })
        } } catch { /* ungültiges Muster meldet die Definition-Prüfung */ }
      }
      if (c.minDate && val < c.minDate) {
        errs.push({ path: key, code: 'MIN_DATE', message: `nicht vor ${c.minDate}` })
      }
      if (c.maxDate && val > c.maxDate) {
        errs.push({ path: key, code: 'MAX_DATE', message: `nicht nach ${c.maxDate}` })
      }
    }
    if (c && typeof val === 'number') {
      if (c.min != null && val < c.min) {
        errs.push({ path: key, code: 'MIN', message: `mindestens ${c.min}` })
      }
      if (c.max != null && val > c.max) {
        errs.push({ path: key, code: 'MAX', message: `höchstens ${c.max}` })
      }
    }
  }
  return errs
}

/** Pass 2: Kann die Phase abgeschlossen werden? */
export function validatePhaseCompletion(
  defn: ProcessDefinition, phase: PhaseDef, values: Record<string, unknown>,
): SimFieldError[] {
  const errs: SimFieldError[] = []
  const byKey = new Map(defn.fields.map((f) => [f.key, f]))
  for (const ref of phase.fields) {
    if (ref.mode === 'hidden') continue
    if (!byKey.has(ref.ref)) continue
    if (ref.visibleWhen && !evaluate(ref.visibleWhen as Condition, values)) continue
    const required = ref.required
      || (!!ref.requiredWhen && evaluate(ref.requiredWhen as Condition, values))
    if (required && isEmpty(values[ref.ref])) {
      errs.push({ path: ref.ref, code: 'REQUIRED', message: 'Pflichtfeld' })
    }
  }
  phase.constraints.forEach((c, i) => {
    if (!evaluate(c.when as Condition, values)) {
      errs.push({ path: `${phase.key}.constraints[${i}]`, code: 'CONSTRAINT',
        message: c.message || 'Regel nicht erfüllt' })
    }
  })
  return errs
}

// ── Laufzeit (Spiegel process_runtime) ────────────────────────────────────────

export function enterStatusFor(phase: PhaseDef): string {
  if (phase.enterStatus) return phase.enterStatus
  return phase.kind === 'review' ? 'in_request' : 'in_progress'
}

export function initialRuntime(defn: ProcessDefinition, nowIso: string): ProcessRuntime {
  return {
    current_index: 0,
    epoch: 0,
    rejected: false,
    sla_paused_ms: 0,
    phases: defn.phases.map((p, i) => ({
      key: p.key,
      status: i === 0 ? 'open' : 'pending',
      entered_at: i === 0 ? nowIso : null,
    })),
  }
}

export function currentPhase(defn: ProcessDefinition, rt: ProcessRuntime): PhaseDef | null {
  const i = rt.current_index
  return i >= 0 && i < defn.phases.length ? defn.phases[i] : null
}

export function isTerminal(defn: ProcessDefinition, rt: ProcessRuntime): boolean {
  return rt.rejected || rt.current_index >= defn.phases.length
}

export function advance(
  defn: ProcessDefinition, rt: ProcessRuntime, nowIso: string,
): { runtime: ProcessRuntime; status: string } {
  const next: ProcessRuntime = JSON.parse(JSON.stringify(rt))
  next.phases[next.current_index].status = 'done'
  next.current_index += 1
  if (next.current_index >= defn.phases.length) return { runtime: next, status: 'archived' }
  const entry = next.phases[next.current_index]
  entry.status = 'open'
  entry.entered_at = nowIso
  return { runtime: next, status: enterStatusFor(defn.phases[next.current_index]) }
}

export function resolveResponsibility(
  phase: PhaseDef, values: Record<string, unknown>,
): { kind: string; group?: string; user?: string; departments?: { group: string; required: boolean }[] } {
  const r = phase.responsibility
  if (r.kind === 'departments') {
    return {
      kind: 'departments',
      departments: r.rule
        .filter((dr) => !dr.when || evaluate(dr.when as Condition, values))
        .map((dr) => ({ group: dr.group, required: dr.required })),
    }
  }
  if (r.kind === 'group') return { kind: 'group', group: r.group ?? '' }
  if (r.kind === 'user') return { kind: 'user', user: r.user ?? '' }
  return { kind: r.kind }
}

// ── Simulator-Sitzung (für die Vorschau) ──────────────────────────────────────

export interface SimEvent { at: string; text: string }

export interface SimState {
  runtime: ProcessRuntime
  status: string
  values: Record<string, unknown>
  events: SimEvent[]
}

const MAX_CHAIN = 20

export function startSim(defn: ProcessDefinition, nowIso = new Date().toISOString()): SimState {
  const runtime = initialRuntime(defn, nowIso)
  return {
    runtime,
    status: defn.phases.length ? enterStatusFor(defn.phases[0]) : 'in_progress',
    values: applyComputed(defn.fields, {}),
    events: [{ at: nowIso, text: `Prozess gestartet – Phase „${defn.phases[0]?.label || defn.phases[0]?.key || '—'}"` }],
  }
}

export function simSetValues(
  defn: ProcessDefinition, state: SimState, patch: Record<string, unknown>,
): SimState {
  const values = applyComputed(defn.fields, { ...state.values, ...patch })
  return { ...state, values }
}

/** Phase abschließen. Gibt Fehler zurück, wenn die Pflichtprüfung greift. */
export function simAdvance(
  defn: ProcessDefinition, state: SimState, nowIso = new Date().toISOString(),
): { state: SimState; errors: SimFieldError[] } {
  const phase = currentPhase(defn, state.runtime)
  if (!phase) return { state, errors: [] }
  const errors = validatePhaseCompletion(defn, phase, state.values)
  if (errors.length) return { state, errors }

  let cur = { ...state }
  for (let i = 0; i < MAX_CHAIN; i++) {
    const from = currentPhase(defn, cur.runtime)
    const { runtime, status } = advance(defn, cur.runtime, nowIso)
    const to = currentPhase(defn, runtime)
    cur = {
      runtime,
      status,
      values: cur.values,
      events: [...cur.events, {
        at: nowIso,
        text: to
          ? `„${from?.label || from?.key}" abgeschlossen → „${to.label || to.key}" (${status})`
          : `„${from?.label || from?.key}" abgeschlossen → archiviert`,
      }],
    }
    if (!to) break
    // auto_advance-Automationen der neu betretenen Phase nachbilden
    const auto = [...defn.automations, ...to.automations].find(
      (a) => a.trigger.type === 'on_enter' && a.action.type === 'auto_advance'
        && (!a.guard || evaluate(a.guard as Condition, cur.values)))
    if (!auto) break
    if (i === MAX_CHAIN - 1) {
      cur.events.push({ at: nowIso, text: 'Automatisches Weiterschalten abgebrochen (zu viele Schritte)' })
    }
  }
  return { state: cur, errors: [] }
}

export function simReject(state: SimState, nowIso = new Date().toISOString()): SimState {
  return {
    ...state,
    runtime: { ...state.runtime, rejected: true },
    status: 'rejected',
    events: [...state.events, { at: nowIso, text: 'Auftrag abgelehnt' }],
  }
}
