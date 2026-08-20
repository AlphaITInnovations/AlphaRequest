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
  Action, ApprovalOnReject, ApprovalSpec, Automation, Condition, CreatePermissions, LayoutItem,
  DocumentSpec, LayoutSection, DepartmentRule, FieldConstraints, FieldDef, FieldRef,
  FieldVisibility, PhaseConstraint, PhaseDef, ProcessDefinition, Responsibility,
  StaticOption, SubField, Trigger,
} from '@/types/process'
import { SCHEMA_VERSION, blankApproval } from '@/lib/processSchema'

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
    computed: from
      ? { from: String(from),
          map: (v?.computed?.map && typeof v.computed.map === 'object') ? v.computed.map : null }
      : null,
    overridable: bool(v?.overridable),
    // `action` ist serverseitig Pflicht und darf nur assign_sequence sein –
    // fehlt sie, wäre das Feld ohne Ersatz unspeicherbar (422 statt Meldung).
    assign: v?.assign
      ? { action: v.assign.action ?? 'assign_sequence', counter: str(v.assign.counter),
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
    fromField: str(v?.fromField),
    rule: arr(v?.rule).map(normDepartmentRule),
    resetOnDescriptionChange: bool(v?.resetOnDescriptionChange),
    notifyOnEnter: bool(v?.notifyOnEnter, true),
  }
}

function normCreatePermissions(v: any): CreatePermissions {
  return {
    everyone: bool(v?.everyone),
    groups: arr(v?.groups).map((g) => String(g)).filter(Boolean),
    users: arr(v?.users).map((u) => String(u)).filter(Boolean),
  }
}

function normLayoutItem(v: any): LayoutItem | null {
  const t = v?.type
  if (t === 'field') return { type: 'field', ref: String(v.ref ?? ''), width: v.width ?? 'full' }
  if (t === 'note') {
    return { type: 'note', text: String(v.text ?? ''), tone: v.tone ?? 'info',
      width: v.width ?? 'full', visibleWhen: cond(v.visibleWhen) }
  }
  if (t === 'heading') return { type: 'heading', text: String(v.text ?? '') }
  if (t === 'divider') return { type: 'divider' }
  if (t === 'spacer') return { type: 'spacer' }
  return null   // unbekannter Typ wird verworfen (der Server lehnt ihn ohnehin ab)
}

function normLayoutSection(v: any): LayoutSection {
  return {
    type: 'section',
    title: String(v?.title ?? ''),
    variant: v?.variant ?? 'default',
    badge: str(v?.badge),
    description: str(v?.description),
    collapsed: bool(v?.collapsed),
    items: arr(v?.items).map(normLayoutItem).filter((x): x is LayoutItem => x !== null),
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
    counter: str(v?.counter),
  }
}

/**
 * Freigabe-Block. FEHLT er, bleibt es bei `null` – hier darf nichts erfunden
 * werden: der Server verbietet `approval` bei jeder Phasenart außer approval,
 * und ein hinzugedichteter Block würde jede Definition als geändert zeigen.
 * Ist er DA, werden alle Keys mit den Server-Defaults aufgefüllt (der Server
 * liefert sie ebenfalls vollständig zurück → stabiler Dirty-Vergleich).
 */
function normApproval(v: any): ApprovalSpec | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null
  const d = blankApproval()
  return {
    question: String(v.question ?? ''),
    approveLabel: str(v.approveLabel) ?? d.approveLabel,
    rejectLabel: str(v.rejectLabel) ?? d.rejectLabel,
    externalLink: bool(v.externalLink, d.externalLink),
    emailBody: str(v.emailBody),
    linkMaxAge: str(v.linkMaxAge) ?? d.linkMaxAge,
    requireReason: bool(v.requireReason, d.requireReason),
    decisionField: str(v.decisionField),
    reasonField: str(v.reasonField),
    onReject: (str(v.onReject) ?? d.onReject) as ApprovalOnReject,
  }
}

export function normalizeAutomation(v: any): Automation {
  return { id: String(v?.id ?? ''), trigger: normTrigger(v?.trigger),
    guard: cond(v?.guard), action: normAction(v?.action) }
}

/** Dokument-Vorlage. FEHLT sie, bleibt es bei `null` (der Server verbietet sie
 *  bei jeder Ansicht außer view=document). Ist sie DA, werden alle Keys gefüllt. */
function normDocument(v: any): DocumentSpec | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null
  const bindings: Record<string, string> = {}
  if (v.bindings && typeof v.bindings === 'object' && !Array.isArray(v.bindings)) {
    for (const [k, val] of Object.entries(v.bindings)) {
      if (val) bindings[String(k)] = String(val)
    }
  }
  return {
    templateHtml: String(v.templateHtml ?? ''),
    filename: String(v.filename ?? 'Dokument'),
    title: String(v.title ?? 'Dokument'),
    bindings,
  }
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
    approval: normApproval(v?.approval),
    document: normDocument(v?.document),
    fields: arr(v?.fields).map(normalizeFieldRef),
    layout: arr(v?.layout).map(normLayoutSection),
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
    titleEditable: bool(v?.titleEditable, true),   // Default true (wie der Server)
    titleTemplate: str(v?.titleTemplate),
    createPermissions: normCreatePermissions(v?.createPermissions),
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
