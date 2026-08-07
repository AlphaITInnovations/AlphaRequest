/**
 * Laufzeit-Begleiter zu types/process.ts: Whitelists, Schlüssel-Regeln, Labels
 * und Leer-Vorlagen.
 *
 * WICHTIG: Der Editor darf ausschließlich anbieten, was das Backend auch
 * annimmt. Das Backend lehnt beim Speichern ab, was die Laufzeit (noch) nicht
 * umsetzt – siehe UNIMPLEMENTED_* in backend/schemas/process_definition.py.
 * Wird dort etwas nachgerüstet, gehören die Werte HIER wieder hinein.
 */
import type {
  ActionType, Automation, DepartmentRule, FieldDef, FieldMode, FieldRef, OptionsSource,
  PhaseDef, PhaseKind, PhaseView, ProcessDefinition, Responsibility, ResponsibilityKind,
  SubField, Widget,
} from '@/types/process'

// ── Whitelists (nur serverseitig Erlaubtes) ───────────────────────────────────

/** Widgets im Feld-Katalog: server_generated/server_stamped sind hier verboten. */
export const WIDGETS_TOP: readonly Widget[] = [
  'text', 'textarea', 'number', 'date', 'select', 'multiselect', 'checkbox',
  'checkbox-group', 'attachment', 'user', 'company', 'group', 'collection',
]

/** Widgets in collection-Unterfeldern: kein collection, aber server_stamped erlaubt. */
export const WIDGETS_SUB: readonly Widget[] = [
  'text', 'textarea', 'number', 'date', 'select', 'multiselect', 'checkbox',
  'checkbox-group', 'attachment', 'user', 'company', 'group', 'server_stamped',
]

export const PHASE_KINDS: readonly PhaseKind[] = ['start', 'task', 'review', 'end']
export const PHASE_VIEWS: readonly PhaseView[] = ['form', 'readonly', 'review']
export const RESPONSIBILITY_KINDS: readonly ResponsibilityKind[] =
  ['owner', 'group', 'user', 'departments', 'originator']
export const FIELD_MODES: readonly FieldMode[] = ['editable', 'readonly', 'hidden', 'append_only']
export const OPTIONS_SOURCES: readonly OptionsSource[] = ['static', 'groups', 'companies', 'users']
export const TRIGGER_TYPES = ['on_enter', 'on_exit', 'on_field_change', 'timer'] as const

/** Actions ohne die serverseitig abgelehnten (spawn_process/assign_sequence/require_attachment). */
export const ACTION_TYPES: readonly ActionType[] = [
  'notify', 'escalate', 'set_field', 'set_priority', 'set_status', 'auto_advance',
]

/** enterStatus/set_status: terminale Status sind verboten. */
export const ENTER_STATUS: readonly string[] = ['in_progress', 'in_request', 'waiting_contract']
export const PRIORITIES: readonly string[] = ['low', 'normal', 'high', 'urgent']
/** Feste Empfänger-Ziele; zusätzlich ist 'group:<id>' erlaubt. */
export const RECIPIENTS: readonly string[] = ['responsible', 'owner', 'watchers']

export const SCHEMA_VERSION = 1

// ── Schlüssel-Regeln (drei verschiedene Alphabete!) ───────────────────────────

/** Prozess-Key: Slug, kleingeschrieben, beginnt alphanumerisch, kein Unterstrich. */
export const RE_PROCESS_KEY = /^[a-z0-9][a-z0-9-]{0,63}$/
/** Phasen-Key: nur a-z, 0-9, Unterstrich – keine Bindestriche, keine Punkte. */
export const RE_PHASE_KEY = /^[a-z0-9_]+$/
/** Feld-Key: Punkt-Pfad, Segmente aus A-Z, a-z, 0-9, Unterstrich. */
export const RE_FIELD_SEGMENT = /^[A-Za-z0-9_]+$/

export function isValidProcessKey(v: string): boolean {
  return RE_PROCESS_KEY.test(v || '')
}
export function isValidPhaseKey(v: string): boolean {
  return RE_PHASE_KEY.test(v || '')
}
export function isValidFieldKey(v: string): boolean {
  if (!v) return false
  return v.split('.').every((seg) => RE_FIELD_SEGMENT.test(seg))
}

/** Vorschlag für einen Prozess-Key aus einem Namen (nur Vorschlag, editierbar). */
export function suggestProcessKey(name: string): string {
  const base = (name || '')
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => ({ ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' } as Record<string, string>)[c] || c)
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
  return base.replace(/^[^a-z0-9]+/, '') || 'prozess'
}

/** Vorschlag für einen Phasen-Key (anderes Alphabet: Unterstriche statt Bindestriche). */
export function suggestPhaseKey(label: string): string {
  const base = (label || '')
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => ({ ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' } as Record<string, string>)[c] || c)
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return base || 'phase'
}

// ── Deutsche Labels für die Oberfläche ────────────────────────────────────────

export const WIDGET_LABEL: Record<Widget, string> = {
  text: 'Text', textarea: 'Mehrzeiliger Text', number: 'Zahl', date: 'Datum',
  select: 'Auswahl', multiselect: 'Mehrfachauswahl', checkbox: 'Ja/Nein',
  'checkbox-group': 'Ankreuzliste', attachment: 'Datei-Anhang',
  user: 'Person', company: 'Firma', group: 'Fachabteilung',
  collection: 'Wiederholgruppe', server_generated: 'Systemwert (nicht verfügbar)',
  server_stamped: 'Systemstempel',
}

export const PHASE_KIND_LABEL: Record<PhaseKind, string> = {
  start: 'Start', task: 'Bearbeitung', approval: 'Freigabe (nicht verfügbar)',
  review: 'Fachabteilungen', end: 'Abschluss',
}

export const PHASE_VIEW_LABEL: Record<PhaseView, string> = {
  form: 'Formular', readonly: 'Nur lesen', approval: 'Freigabe (nicht verfügbar)',
  review: 'Prüfung', export: 'Export (nicht verfügbar)',
}

export const RESPONSIBILITY_LABEL: Record<ResponsibilityKind, string> = {
  owner: 'Ersteller:in', group: 'Feste Fachabteilung', user: 'Feste Person',
  departments: 'Mehrere Fachabteilungen', originator: 'Auslösende Person',
}

export const FIELD_MODE_LABEL: Record<FieldMode, string> = {
  editable: 'Bearbeitbar', readonly: 'Nur lesen', hidden: 'Ausgeblendet',
  append_only: 'Nur anhängen',
}

export const TRIGGER_LABEL: Record<string, string> = {
  on_enter: 'Beim Betreten der Phase', on_exit: 'Beim Verlassen der Phase',
  on_field_change: 'Bei Feldänderung', timer: 'Zeitgesteuert',
}

export const ACTION_LABEL: Record<string, string> = {
  notify: 'Benachrichtigen', escalate: 'Eskalieren', set_field: 'Feld setzen',
  set_priority: 'Priorität setzen', set_status: 'Status setzen',
  auto_advance: 'Automatisch weiterschalten',
  assign_sequence: 'Nummer vergeben (nicht verfügbar)',
  require_attachment: 'Anhang verlangen (nicht verfügbar)',
  spawn_process: 'Folgeprozess starten (nicht verfügbar)',
}

export const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'In Prüfung',
  waiting_contract: 'Wartet auf Rücklauf', archived: 'Archiviert', rejected: 'Abgelehnt',
}

export const RECIPIENT_LABEL: Record<string, string> = {
  responsible: 'Zuständige Stelle', owner: 'Ersteller:in', watchers: 'Beobachter:innen',
}

// ── Leer-Vorlagen (normalisierte Form) ────────────────────────────────────────

export function blankConstraints() {
  return { pattern: null, minLength: null, maxLength: null, min: null, max: null,
    minDate: null, maxDate: null }
}

export function blankFieldDef(key = '', widget: Widget = 'text'): FieldDef {
  return {
    key, label: null, widget, help: null, placeholder: null,
    options: [], optionsSource: null, allowOther: false, valueShape: null,
    constraints: null, visibility: null, computed: null, overridable: false,
    assign: null, mode: null, item: [],
  }
}

export function blankSubField(key = '', widget: Widget = 'text'): SubField {
  return { key, label: null, widget, value: null }
}

/** ACHTUNG: required=false – anders als bei DepartmentRule. */
export function blankFieldRef(ref: string): FieldRef {
  return { ref, mode: 'editable', required: false, requiredWhen: null, visibleWhen: null }
}

/** ACHTUNG: required=true – anders als bei FieldRef. */
export function blankDepartmentRule(group = ''): DepartmentRule {
  return { group, required: true, when: null }
}

export function blankResponsibility(kind: ResponsibilityKind = 'owner'): Responsibility {
  return { kind, group: null, user: null, rule: [], resetOnDescriptionChange: false }
}

export function blankPhase(key: string, kind: PhaseKind = 'task'): PhaseDef {
  return {
    key, label: null, kind, view: kind === 'review' ? 'review' : 'form',
    enterStatus: null, grantsFullView: false,
    responsibility: blankResponsibility(kind === 'review' ? 'departments' : 'owner'),
    fields: [], constraints: [], automations: [],
  }
}

export function blankAutomation(id: string): Automation {
  return {
    id,
    trigger: { type: 'on_enter', after: null, repeat: null, field: null },
    guard: null,
    action: { type: 'notify', to: 'responsible', template: null, field: null,
      value: null, process: null, counter: null },
  }
}

export function blankDefinition(key: string, name: string): ProcessDefinition {
  return {
    schemaVersion: SCHEMA_VERSION, key, name, description: null, icon: null,
    fields: [],
    phases: [blankPhase('erstellung', 'start')],
    automations: [],
  }
}
