/**
 * Laufzeit-Begleiter zu types/process.ts: Whitelists, Schlüssel-Regeln, Labels
 * und Leer-Vorlagen.
 *
 * WICHTIG: Der Editor darf ausschließlich anbieten, was das Backend auch
 * annimmt – nicht mehr und nicht weniger. Das Backend lehnt beim Speichern ab,
 * was die Laufzeit nicht umsetzt (UNIMPLEMENTED_* in
 * backend/schemas/process_definition.py; die Mengen sind derzeit LEER, es ist
 * also alles nutzbar, was das Schema kennt). Wird dort künftig ein Wert
 * eingetragen, gehört er HIER aus der Whitelist heraus.
 */
import type {
  LayoutItem, LayoutItemType, LayoutSection, LayoutWidth, NoteTone, SectionVariant,
  ActionType, ApprovalSpec, AssignSpec, Automation, DepartmentRule, DocumentSpec, FieldDef, FieldMode,
  FieldRef, OptionsSource,
  CreatePermissions, PhaseDef, PhaseKind, PhaseView, ProcessDefinition, Responsibility, ResponsibilityKind,
  SubField, Widget,
} from '@/types/process'

// ── Whitelists (nur serverseitig Erlaubtes) ───────────────────────────────────

/** Widgets im Feld-Katalog: server_stamped gibt es nur in collection-Unterfeldern. */
export const WIDGETS_TOP: readonly Widget[] = [
  'text', 'textarea', 'number', 'date', 'select', 'multiselect', 'checkbox',
  'checkbox-group', 'attachment', 'user', 'company', 'group', 'collection',
  'server_generated',
]

/** Widgets in collection-Unterfeldern: kein collection, aber server_stamped erlaubt. */
// Auswahl-Widgets fehlen bewusst: SubField trägt serverseitig KEINE Optionen,
// ein Auswahlfeld bliebe damit dauerhaft leer.
export const WIDGETS_SUB: readonly Widget[] = [
  'text', 'textarea', 'number', 'date', 'checkbox',
  'attachment', 'user', 'company', 'group', 'server_stamped',
]

export const PHASE_KINDS: readonly PhaseKind[] = ['start', 'task', 'approval', 'review', 'end']
export const PHASE_VIEWS: readonly PhaseView[] =
  ['form', 'readonly', 'approval', 'review', 'export', 'document']
export const RESPONSIBILITY_KINDS: readonly ResponsibilityKind[] =
  ['owner', 'assignable', 'group', 'group_from_field', 'departments', 'user']
export const FIELD_MODES: readonly FieldMode[] = ['editable', 'readonly', 'hidden', 'append_only']
export const OPTIONS_SOURCES: readonly OptionsSource[] = ['static', 'groups', 'companies', 'users']
export const TRIGGER_TYPES = ['on_enter', 'on_exit', 'on_field_change', 'timer'] as const

export const ACTION_TYPES: readonly ActionType[] = [
  'notify', 'escalate', 'set_field', 'set_priority', 'set_status', 'assign_sequence',
  'auto_advance',
]

/**
 * Nummernkreise, die die Laufzeit kennt (Spiegel von KNOWN_COUNTERS in
 * backend/services/process_sequences.py). Das Meta-Schema prüft den Namen NICHT –
 * ein unbekannter Nummernkreis lässt sich also speichern und scheitert erst beim
 * Phasenabschluss. Der Editor warnt deshalb, blockiert aber nicht.
 */
export const SEQUENCE_COUNTERS: readonly string[] = ['personalnummer']

export const COUNTER_LABEL: Record<string, string> = {
  personalnummer: 'Personalnummer (Nummernkreis je Firma)',
}

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

/** approval.onReject: „reject" oder „back_to:<phasen_key>" (Phasen-Alphabet!). */
export const RE_BACK_TO = /^back_to:([a-z0-9_]+)$/

/** Phasen-Key aus einem `back_to:…` – null bei „reject" oder kaputter Form. */
export function backToTarget(onReject: string): string | null {
  return RE_BACK_TO.exec(onReject || '')?.[1] ?? null
}

export function isValidOnReject(v: string): boolean {
  return v === 'reject' || RE_BACK_TO.test(v || '')
}

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
  collection: 'Wiederholgruppe', server_generated: 'Vom System vergebene Nummer',
  server_stamped: 'Systemstempel',
}

export const PHASE_KIND_LABEL: Record<PhaseKind, string> = {
  start: 'Start', task: 'Bearbeitung', approval: 'Freigabe',
  review: 'Fachabteilungen', end: 'Abschluss',
}

export const PHASE_VIEW_LABEL: Record<PhaseView, string> = {
  form: 'Formular', readonly: 'Nur lesen', approval: 'Freigabe',
  review: 'Prüfung', export: 'Export', document: 'Dokument',
}

export const RESPONSIBILITY_LABEL: Record<ResponsibilityKind, string> = {
  owner: 'Ersteller:in',
  assignable: 'Person aus einem Feld (bei Erstellung gewählt)',
  group: 'Feste Fachabteilung',
  group_from_field: 'Fachabteilung aus einem Feld (bei Erstellung gewählt)',
  user: 'Feste Person',
  departments: 'Mehrere Fachabteilungen',
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
  assign_sequence: 'Nummer aus Nummernkreis vergeben',
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

/**
 * Vergabe-Angaben eines server_generated-Feldes. `action` ist fix: der Server
 * lässt ausschließlich assign_sequence zu.
 */
export function blankAssign(): AssignSpec {
  return { action: 'assign_sequence', counter: SEQUENCE_COUNTERS[0], companyRef: null }
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
  return { kind, group: null, user: null, fromField: null, rule: [],
    resetOnDescriptionChange: false, notifyOnEnter: true }
}

/**
 * Freigabe-Block mit den SERVER-Defaults. Die Werte müssen mit ApprovalSpec in
 * backend/schemas/process_definition.py übereinstimmen – sonst gilt eine frisch
 * geladene Definition sofort als geändert (canonicalJson-Vergleich).
 */
export function blankApproval(question = ''): ApprovalSpec {
  return {
    question,
    approveLabel: 'Freigeben',
    rejectLabel: 'Ablehnen',
    externalLink: true,
    emailBody: null,
    linkMaxAge: 'P7D',
    requireReason: true,
    decisionField: null,
    reasonField: null,
    onReject: 'reject',
  }
}

/** Leere Dokument-Vorlage (view=document). Ein Start-Template, damit die Phase
 *  gültig ist; die eigentliche Vorlage wird darunter bearbeitet. */
export function blankDocument(): DocumentSpec {
  // Neuer Standard: eine hochgeladene .docx-Vorlage + Marker-Zuordnung (bindings).
  // templateHtml bleibt leer (nur noch Alt-Prozesse nutzen den HTML-Weg).
  // Dateiname OHNE Platzhalter: ein {{feld}}-Default würde bei Prozessen ohne
  // genau dieses Feld sofort einen UNKNOWN_REF-Fehler werfen und das Speichern
  // sperren (der Admin kann später eigene Platzhalter eintragen).
  return {
    templateHtml: '',
    filename: 'Dokument',
    title: 'Dokument',
    bindings: {},
  }
}

/** Passende Standard-Ansicht zur Phasenart (view=approval nur bei kind=approval). */
export function defaultViewFor(kind: PhaseKind): PhaseView {
  if (kind === 'approval') return 'approval'
  if (kind === 'review') return 'review'
  return 'form'
}

export function blankPhase(key: string, kind: PhaseKind = 'task'): PhaseDef {
  return {
    key, label: null, kind, view: defaultViewFor(kind),
    enterStatus: null, advanceLabel: null, grantsFullView: false,
    responsibility: blankResponsibility(kind === 'review' ? 'departments' : 'owner'),
    approval: kind === 'approval' ? blankApproval() : null,
    document: null,
    fields: [], layout: [], constraints: [], automations: [],
  }
}

/**
 * Was sich beim Umstellen der PHASEN-ART zwingend mit ändert.
 *
 * Der Server koppelt drei Dinge fest aneinander: bei `kind=approval` ist der
 * Freigabe-Block Pflicht, bei jeder anderen Art ist er verboten, und
 * `view=approval` gibt es nur dort. Ohne diese Nachführung baut der Editor eine
 * Definition, die er selbst gerade erst abgelehnt bekommt.
 */
export function phaseKindPatch(phase: PhaseDef, kind: PhaseKind): Partial<PhaseDef> {
  const wirdFreigabe = kind === 'approval'
  const viewPasstNichtMehr = phase.view === 'approval' && !wirdFreigabe
  return {
    kind,
    approval: wirdFreigabe ? (phase.approval ?? blankApproval()) : null,
    view: wirdFreigabe || viewPasstNichtMehr ? defaultViewFor(kind) : phase.view,
  }
}

/**
 * Was sich beim Umstellen der ZUSTÄNDIGKEIT mit ändert: nicht mehr passende
 * Angaben fliegen raus, weil der Server sie streng prüft. `fromField` fällt
 * auch beim Wechsel zwischen den beiden „aus einem Feld"-Arten weg – ein
 * Personen-Feld taugt nicht als Fachabteilung und umgekehrt.
 */
export function responsibilityKindPatch(
  cur: Responsibility, kind: ResponsibilityKind,
): Responsibility {
  return {
    ...cur,
    kind,
    group: kind === 'group' ? cur.group : null,
    user: kind === 'user' ? cur.user : null,
    fromField: kind === cur.kind ? cur.fromField : null,
    rule: kind === 'departments'
      ? (cur.rule.length ? cur.rule : [blankDepartmentRule()])
      : [],
  }
}

export function blankAutomation(id: string): Automation {
  return {
    id,
    trigger: { type: 'on_enter', after: null, repeat: null, field: null },
    guard: null,
    action: { type: 'notify', to: 'responsible', template: null, field: null,
      value: null, counter: null },
  }
}

export function blankCreatePermissions(): CreatePermissions {
  // Restriktiver Default: ein neuer Prozess ist zunächst nur für Admins anlegbar.
  return { everyone: false, groups: [], users: [] }
}

export function blankDefinition(key: string, name: string): ProcessDefinition {
  return {
    schemaVersion: SCHEMA_VERSION, key, name, description: null, icon: null,
    titleEditable: true,          // Server-Default; abwählbar in den Kopfdaten
    titleTemplate: null,
    createPermissions: blankCreatePermissions(),
    fields: [],
    phases: [blankPhase('erstellung', 'start')],
    automations: [],
  }
}

// ── Layout ────────────────────────────────────────────────────────────────────

export const LAYOUT_WIDTHS: readonly LayoutWidth[] =
  ['quarter', 'third', 'half', 'twothirds', 'full']

/** Spalten im 12er-Raster – daraus baut der Renderer die Breite. */
export const WIDTH_COLS: Record<LayoutWidth, number> = {
  quarter: 3, third: 4, half: 6, twothirds: 8, full: 12,
}

export const WIDTH_LABEL: Record<LayoutWidth, string> = {
  quarter: '¼', third: '⅓', half: '½', twothirds: '⅔', full: 'Ganz',
}

export const SECTION_VARIANTS: readonly SectionVariant[] =
  ['default', 'base', 'hr', 'it', 'fuhrpark', 'marketing', 'travel']

/** Symbol + Akzentfarben je Variante (gerendert von process/form/LayoutSection.vue). */
export const VARIANT_STYLE: Record<SectionVariant, {
  label: string; icon: string; chip: string; badge: string; bar: string
}> = {
  base: { label: 'Basis', icon: '📋',
    chip: 'bg-[#3EACB6]/15 text-[#0F7683] dark:text-[#5FD3DE]',
    badge: 'bg-[#3EACB6]/15 text-[#0F7683] dark:text-[#5FD3DE]', bar: 'bg-[#3EACB6]' },
  hr: { label: 'Personal', icon: '👤',
    chip: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',
    badge: 'bg-blue-500/15 text-blue-700 dark:text-blue-300', bar: 'bg-blue-500' },
  it: { label: 'IT', icon: '💻',
    chip: 'bg-purple-500/15 text-purple-700 dark:text-purple-300',
    badge: 'bg-purple-500/15 text-purple-700 dark:text-purple-300', bar: 'bg-purple-500' },
  fuhrpark: { label: 'Fuhrpark', icon: '🚗',
    chip: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', bar: 'bg-amber-500' },
  marketing: { label: 'Marketing', icon: '📣',
    chip: 'bg-pink-500/15 text-pink-700 dark:text-pink-300',
    badge: 'bg-pink-500/15 text-pink-700 dark:text-pink-300', bar: 'bg-pink-500' },
  travel: { label: 'Reise', icon: '✈️',
    chip: 'bg-teal-500/15 text-teal-700 dark:text-teal-300',
    badge: 'bg-teal-500/15 text-teal-700 dark:text-teal-300', bar: 'bg-teal-500' },
  default: { label: 'Neutral', icon: '🗂',
    chip: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
    badge: 'bg-slate-500/15 text-slate-600 dark:text-slate-300', bar: 'bg-slate-400' },
}

export const NOTE_TONES: readonly NoteTone[] = ['info', 'warning', 'success', 'neutral']

export const NOTE_STYLE: Record<NoteTone, { label: string; icon: string; box: string }> = {
  info: { label: 'Hinweis', icon: 'ℹ️',
    box: 'border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200' },
  warning: { label: 'Achtung', icon: '⚠️',
    box: 'border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200' },
  success: { label: 'Erledigt', icon: '✅',
    box: 'border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200' },
  neutral: { label: 'Neutral', icon: '📝',
    box: 'border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 text-gray-700 dark:text-gray-300' },
}

export const LAYOUT_ITEM_LABEL: Record<LayoutItemType, string> = {
  field: 'Feld', note: 'Hinweisbox', heading: 'Zwischen-Überschrift',
  divider: 'Trennlinie', spacer: 'Abstand',
}

export function blankSection(title = 'Neuer Abschnitt',
                             variant: SectionVariant = 'default'): LayoutSection {
  return { type: 'section', title, variant, badge: null, description: null,
    collapsed: false, items: [] }
}

export function blankLayoutItem(type: LayoutItemType, ref = ''): LayoutItem {
  switch (type) {
    case 'field': return { type: 'field', ref, width: 'half' }
    case 'note': return { type: 'note', text: '', tone: 'info', width: 'full' }
    case 'heading': return { type: 'heading', text: '' }
    case 'divider': return { type: 'divider' }
    default: return { type: 'spacer' }
  }
}

/** Alle im Layout platzierten Feld-Refs (über alle Abschnitte). */
export function placedRefs(layout: LayoutSection[]): Set<string> {
  const out = new Set<string>()
  for (const sec of layout || []) {
    for (const it of sec.items || []) if (it.type === 'field') out.add(it.ref)
  }
  return out
}
