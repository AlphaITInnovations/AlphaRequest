/**
 * Normalisierung einer ProcessDefinition auf die vollständige Form
 * (jeder Key vorhanden, `null` statt fehlend).
 *
 * Warum: Der Server liefert dank `model_dump(by_alias=True)` immer ALLE Keys
 * zurück. Vergleicht man einen selbst gebauten Entwurf naiv mit der Server-
 * Antwort, ist er sofort „dirty", obwohl sich nichts geändert hat. Normalisieren
 * beide Seiten → stabiler Dirty-Vergleich (canonicalJson).
 *
 * Außerdem: `computed.from_` (Python-Feldname) wird beim Einlesen akzeptiert,
 * ausgegeben wird IMMER `from` (der Wire-Name).
 */
import type {
  Action, Automation, Condition, DepartmentRule, FieldConstraints, FieldDef, FieldRef,
  FieldVisibility, PhaseConstraint, PhaseDef, ProcessDefinition, Responsibility,
  StaticOption, SubField, Trigger,
} from '@/types/process'
import { SCHEMA_VERSION } from '@/lib/processSchema'

const str = (v: unknown): string | null =>
  v === undefined || v === null || v === '' ? null : String(v)
const num = (v: unknown): number | null =>
  v === undefined || v === null || v === '' || Number.isNaN(Number(v)) ? null : Number(v)
const bool = (v: unknown, dflt = false): boolean => (v === undefined || v === null ? dflt : !!v)
const arr = (v: unknown): any[] => (Array.isArray(v) ? v : [])
const cond = (v: unknown): Condition | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Condition) : null

function normConstraints(v: any): FieldConstraints | null {
  if (!v || typeof v !== 'object') return null
  return {
    pattern: str(v.pattern), minLength: num(v.minLength), maxLength: num(v.maxLength),
    min: num(v.min), max: num(v.max), minDate: str(v.minDate), maxDate: str(v.maxDate),
  }
}

function normVisibility(v: any): FieldVisibility | null {
  if (!v || typeof v !== 'object') return null
  return {
    confidential: bool(v.confidential),
    visibleToGroups: arr(v.visibleToGroups).map((g) => String(g)).filter(Boolean),
  }
}

function normOptions(v: unknown): StaticOption[] {
  return arr(v).map((o) =>
    typeof o === 'string'
      ? { value: o, label: null }
      : { value: String(o?.value ?? ''), label: str(o?.label) })
}

function normSubField(v: any): SubField {
  return { key: String(v?.key ?? ''), label: str(v?.label), widget: v?.widget ?? 'text',
    value: str(v?.value) }
}

export function normalizeField(v: any): FieldDef {
  // `from_` (Python-Feldname) beim Einlesen tolerieren, `from` ausgeben.
  const from = v?.computed?.from ?? v?.computed?.from_
  return {
    key: String(v?.key ?? ''),
    label: str(v?.label),
    widget: v?.widget ?? 'text',
    help: str(v?.help),
    placeholder: str(v?.placeholder),
    options: normOptions(v?.options),
    optionsSource: v?.optionsSource ?? null,
    allowOther: bool(v?.allowOther),
    valueShape: str(v?.valueShape),
    constraints: normConstraints(v?.constraints),
    visibility: normVisibility(v?.visibility),
    computed: from ? { from: String(from) } : null,
    overridable: bool(v?.overridable),
    assign: v?.assign
      ? { action: v.assign.action, counter: str(v.assign.counter),
        companyRef: str(v.assign.companyRef) }
      : null,
    mode: v?.mode ?? null,
    item: arr(v?.item).map(normSubField),
  }
}

export function normalizeFieldRef(v: any): FieldRef {
  return {
    ref: String(v?.ref ?? ''),
    mode: v?.mode ?? 'editable',
    required: bool(v?.required, false),        // Default false
    requiredWhen: cond(v?.requiredWhen),
    visibleWhen: cond(v?.visibleWhen),
  }
}

function normDepartmentRule(v: any): DepartmentRule {
  return {
    group: String(v?.group ?? ''),
    required: bool(v?.required, true),         // Default true (anders als FieldRef!)
    when: cond(v?.when),
  }
}

function normResponsibility(v: any): Responsibility {
  return {
    kind: v?.kind ?? 'owner',
    group: str(v?.group),
    user: str(v?.user),
    rule: arr(v?.rule).map(normDepartmentRule),
    resetOnDescriptionChange: bool(v?.resetOnDescriptionChange),
  }
}

function normTrigger(v: any): Trigger {
  return { type: v?.type ?? 'on_enter', after: str(v?.after), repeat: str(v?.repeat),
    field: str(v?.field) }
}

function normAction(v: any): Action {
  return {
    type: v?.type ?? 'notify',
    to: str(v?.to),
    template: str(v?.template),
    field: str(v?.field),
    value: v?.value === undefined ? null : v.value,
    process: str(v?.process),
    counter: str(v?.counter),
  }
}

export function normalizeAutomation(v: any): Automation {
  return { id: String(v?.id ?? ''), trigger: normTrigger(v?.trigger),
    guard: cond(v?.guard), action: normAction(v?.action) }
}

/** Extra-Keys bleiben erhalten – der Server verbietet sie hier NICHT. */
function normConstraintEntry(v: any): PhaseConstraint {
  return { ...(v ?? {}), when: cond(v?.when) ?? {}, message: String(v?.message ?? '') }
}

export function normalizePhase(v: any): PhaseDef {
  const kind = v?.kind ?? 'task'
  return {
    key: String(v?.key ?? ''),
    label: str(v?.label),
    kind,
    view: v?.view ?? 'form',
    enterStatus: str(v?.enterStatus),
    grantsFullView: bool(v?.grantsFullView),
    responsibility: normResponsibility(v?.responsibility),
    fields: arr(v?.fields).map(normalizeFieldRef),
    constraints: arr(v?.constraints).map(normConstraintEntry),
    automations: arr(v?.automations).map(normalizeAutomation),
  }
}

export function normalizeDefinition(v: any): ProcessDefinition {
  return {
    schemaVersion: num(v?.schemaVersion) ?? SCHEMA_VERSION,
    key: String(v?.key ?? ''),
    name: String(v?.name ?? ''),
    description: str(v?.description),
    icon: str(v?.icon),
    fields: arr(v?.fields).map(normalizeField),
    phases: arr(v?.phases).map(normalizePhase),
    automations: arr(v?.automations).map(normalizeAutomation),
  }
}

/** Stabile JSON-Form (Keys sortiert) – Basis für den Dirty-Vergleich. */
export function canonicalJson(value: unknown): string {
  const walk = (v: any): any => {
    if (Array.isArray(v)) return v.map(walk)
    if (v && typeof v === 'object') {
      const out: Record<string, any> = {}
      for (const k of Object.keys(v).sort()) out[k] = walk(v[k])
      return out
    }
    return v
  }
  return JSON.stringify(walk(value))
}

export function isSameDefinition(a: unknown, b: unknown): boolean {
  return canonicalJson(normalizeDefinition(a)) === canonicalJson(normalizeDefinition(b))
}

/** Tiefe Kopie über die normalisierte Form (für „Änderungen verwerfen"). */
export function cloneDefinition(d: ProcessDefinition): ProcessDefinition {
  return normalizeDefinition(JSON.parse(JSON.stringify(d)))
}
