/**
 * Typen des dynamischen Prozess-Systems – Spiegel von
 * backend/schemas/process_definition.py und der REST-Antworten.
 *
 * Zwei Ausprägungen pro Modell:
 *  - die NORMALISIERTE Form (jeder Key vorhanden, `null` statt fehlend) – damit
 *    arbeitet der Editor, damit ist ein Dirty-Vergleich stabil und v-model
 *    schreibt nie in einen fehlenden Key;
 *  - die `…In`-Form (alles optional) als Eingabe von normalizeDefinition().
 *
 * Server-Antwortfelder bleiben snake_case – NICHT umbenennen.
 */

// ── Enums als String-Unions (Backend nutzt (str, Enum) → Wire = das Literal) ──

export type Widget =
  | 'text' | 'textarea' | 'number' | 'date'
  | 'select' | 'multiselect' | 'checkbox' | 'checkbox-group'
  | 'attachment' | 'user' | 'company' | 'group'
  | 'collection' | 'server_generated' | 'server_stamped'

export type OptionsSource = 'static' | 'groups' | 'companies' | 'users'
export type PhaseKind = 'start' | 'task' | 'approval' | 'review' | 'end'
export type PhaseView = 'form' | 'readonly' | 'approval' | 'review' | 'export'
export type ResponsibilityKind =
  | 'owner' | 'group' | 'user' | 'departments' | 'originator'
  /** Zuständige Person steht in einem Personen-Feld des Auftrags. */
  | 'assignable'
export type FieldMode = 'editable' | 'readonly' | 'hidden' | 'append_only'
export type TriggerType = 'on_enter' | 'on_exit' | 'on_field_change' | 'timer'
export type ActionType =
  | 'notify' | 'escalate' | 'set_field' | 'set_priority' | 'set_status'
  | 'assign_sequence' | 'require_attachment' | 'auto_advance' | 'spawn_process'

/** Genau EIN Operator-Key pro Objekt – Shapes siehe lib/conditionDsl.ts. */
export type Condition = Record<string, any>

// ── Feld-Katalog (normalisiert) ───────────────────────────────────────────────

export interface FieldConstraints {
  pattern: string | null
  minLength: number | null
  maxLength: number | null
  min: number | null
  max: number | null
  minDate: string | null
  maxDate: string | null
}

export interface FieldVisibility {
  confidential: boolean
  /** Gruppen-IDs. Bei confidential=true serverseitig Pflicht (nicht leer). */
  visibleToGroups: string[]
}

/** Wire-Name ist `from` (Python: from_ mit alias). */
export interface ComputedSpec { from: string }

export interface AssignSpec {
  action: ActionType
  counter: string | null
  companyRef: string | null
}

export interface StaticOption { value: string; label: string | null }

/** Nur innerhalb widget='collection'. */
export interface SubField {
  key: string
  label: string | null
  widget: Widget
  /** Bei widget='server_stamped': 'actor' | 'now'. */
  value: string | null
}

export interface FieldDef {
  key: string
  label: string | null
  widget: Widget
  help: string | null
  placeholder: string | null
  options: StaticOption[]
  optionsSource: OptionsSource | null
  allowOther: boolean
  valueShape: string | null
  constraints: FieldConstraints | null
  visibility: FieldVisibility | null
  computed: ComputedSpec | null
  overridable: boolean
  assign: AssignSpec | null
  mode: FieldMode | null
  /** Sub-Katalog – nicht leer genau dann, wenn widget='collection'. */
  item: SubField[]
}

// ── Phasen (normalisiert) ─────────────────────────────────────────────────────

export interface FieldRef {
  ref: string
  mode: FieldMode
  /** Default false (Gegensatz zu DepartmentRule.required!). */
  required: boolean
  requiredWhen: Condition | null
  visibleWhen: Condition | null
}

export interface DepartmentRule {
  group: string
  /** Default true (Gegensatz zu FieldRef.required!). */
  required: boolean
  when: Condition | null
}

export interface Responsibility {
  kind: ResponsibilityKind
  group: string | null
  user: string | null
  /** Bei kind='assignable': Schlüssel des Personen-Feldes (widget='user'). */
  fromField: string | null
  rule: DepartmentRule[]
  /** Serverseitig abgelehnt, wenn true (noch nicht umgesetzt). */
  resetOnDescriptionChange: boolean
  /** Beim Betreten der Phase automatisch benachrichtigen (Standard: ja). */
  notifyOnEnter: boolean
}

export interface Trigger {
  type: TriggerType
  after: string | null
  repeat: string | null
  field: string | null
}

export interface Action {
  type: ActionType
  to: string | null
  template: string | null
  field: string | null
  value: unknown | null
  process: string | null
  counter: string | null
}

export interface Automation {
  id: string
  trigger: Trigger
  guard: Condition | null
  action: Action
}

/**
 * Serverseitig `list[dict]` – Extra-Keys sind NICHT verboten. Beim Normalisieren
 * daher nicht auf {when,message} beschneiden (sonst Datenverlust).
 */
export interface PhaseConstraint {
  when: Condition
  message: string
  [k: string]: unknown
}

// ── Layout (nur Darstellung) ──────────────────────────────────────────────────
// Bewusst GETRENNT vom Verhalten: was ein Feld TUT (bearbeitbar/pflicht/bedingt)
// steht in PhaseDef.fields; WO und WIE BREIT es steht, hier. Ohne `layout`
// rendert die Phase wie bisher (alle Felder zweispaltig).

export type LayoutWidth = 'quarter' | 'third' | 'half' | 'twothirds' | 'full'
export type SectionVariant = 'base' | 'hr' | 'it' | 'fuhrpark' | 'marketing' | 'travel' | 'default'
export type NoteTone = 'info' | 'warning' | 'success' | 'neutral'

export interface LayoutFieldItem { type: 'field'; ref: string; width: LayoutWidth }
export interface LayoutNoteItem { type: 'note'; text: string; tone: NoteTone; width: LayoutWidth }
export interface LayoutHeadingItem { type: 'heading'; text: string }
export interface LayoutDividerItem { type: 'divider' }
export interface LayoutSpacerItem { type: 'spacer' }

export type LayoutItem =
  | LayoutFieldItem | LayoutNoteItem | LayoutHeadingItem | LayoutDividerItem | LayoutSpacerItem

export type LayoutItemType = LayoutItem['type']

export interface LayoutSection {
  type: 'section'
  title: string
  variant: SectionVariant
  badge: string | null
  description: string | null
  collapsed: boolean
  items: LayoutItem[]
}

export interface PhaseDef {
  key: string
  label: string | null
  kind: PhaseKind
  view: PhaseView
  enterStatus: string | null
  grantsFullView: boolean
  responsibility: Responsibility
  fields: FieldRef[]
  /** Optionale Darstellung; nicht platzierte Felder kommen in einen Sammel-Abschnitt. */
  layout: LayoutSection[]
  constraints: PhaseConstraint[]
  automations: Automation[]
}

/** Wer darf Aufträge dieses Prozesses ANLEGEN? Teil der Definition, wandert
 *  daher bei Export/Import/Kopie mit. Default = nur Admin. */
export interface CreatePermissions {
  everyone: boolean
  /** Gruppen-IDs (Fachabteilungen ODER AD-Gruppen). */
  groups: string[]
  /** Einzelne Personen (User-IDs). */
  users: string[]
}

export interface ProcessDefinition {
  schemaVersion: number
  key: string
  name: string
  description: string | null
  icon: string | null
  createPermissions: CreatePermissions
  fields: FieldDef[]
  phases: PhaseDef[]
  automations: Automation[]
}

// ── Eingabe-Formen (alles optional) für normalizeDefinition ───────────────────

type Loose<T> = { [K in keyof T]?: any }
export type FieldDefIn = Loose<FieldDef>
export type FieldRefIn = Loose<FieldRef>
export type PhaseDefIn = Loose<PhaseDef>
export type AutomationIn = Loose<Automation>
export type ProcessDefinitionIn = Loose<ProcessDefinition>

// ── Server-Envelopes ──────────────────────────────────────────────────────────

export type ProcessStatus = 'draft' | 'published' | 'archived'

export interface ProcessOut {
  id: number
  key: string
  version: number
  status: ProcessStatus
  name: string
  /** NULL auf Listen-Routen – dort wird definition_json nicht mitgelesen. */
  definition: ProcessDefinition | null
  base_version: number | null
  created_by: string | null
  created_by_name: string | null
  created_at: string | null
  updated_at: string | null
  published_at: string | null
  /** String(rev), ohne Anführungszeichen – für If-Match. */
  etag: string | null
}

export interface ProcessRuntimePhase {
  key: string
  status: 'open' | 'done' | 'pending'
  entered_at: string | null
}

export interface ProcessRuntime {
  current_index: number
  epoch: number
  rejected: boolean
  sla_paused_ms: number
  phases: ProcessRuntimePhase[]
}

export type ResolvedResponsibility =
  | { kind: 'departments'; departments: { group: string; required: boolean; status: string }[] }
  | { kind: 'group'; group: string }
  | { kind: 'user'; user: string }
  | { kind: 'owner' }
  | { kind: 'originator' }
  | { kind: 'unknown' }

export interface ProcessTicketOut {
  id: number
  process_key: string
  process_version: number
  title: string
  status: string
  priority: string
  owner_id: string | null
  owner_name: string | null
  /** Serverseitig nach Sichtbarkeit gefiltert. */
  values: Record<string, unknown>
  runtime: ProcessRuntime
  current_phase: string | null
  current_phase_label: string | null
  responsibility: ResolvedResponsibility | null
  next_timer_due_at: string | null
  created_at: string | null
  updated_at: string | null
}

// ── Editor-interne Typen ──────────────────────────────────────────────────────

export type IssueSeverity = 'error' | 'warning'

export interface ProcessIssue {
  /** Serverkompatibler Pfad, z.B. 'phases.0.fields.2.ref'. */
  path: string
  /** DOM-Anker im Editor, z.B. 'pe-phase-0'. */
  anchor: string
  code: string
  severity: IssueSeverity
  message: string
  source: 'client' | 'server'
}

export interface OptionSources {
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  companies: string[]
}
