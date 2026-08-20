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
export type PhaseView = 'form' | 'readonly' | 'approval' | 'review' | 'export' | 'document'
export type ResponsibilityKind =
  | 'owner' | 'group' | 'user' | 'departments'
  /** Zuständige Person steht in einem Personen-Feld des Auftrags (widget='user'). */
  | 'assignable'
  /** Zuständige Fachabteilung steht in einem Gruppen-Feld des Auftrags (widget='group'). */
  | 'group_from_field'
export type FieldMode = 'editable' | 'readonly' | 'hidden' | 'append_only'
export type TriggerType = 'on_enter' | 'on_exit' | 'on_field_change' | 'timer'
export type ActionType =
  | 'notify' | 'escalate' | 'set_field' | 'set_priority' | 'set_status'
  | 'assign_sequence' | 'auto_advance'

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
export interface ComputedSpec { from: string; map?: Record<string, unknown> | null }

/**
 * Wie ein `server_generated`-Feld gefüllt wird. Serverseitig gilt: `action` muss
 * 'assign_sequence' sein und `counter` (Name des Nummernkreises) ist Pflicht.
 * `companyRef` nennt das Feld mit der Firma – die Nummernkreise sind pro Firma
 * gepflegt (die Laufzeit bricht ohne companyRef beim Phasenabschluss ab).
 */
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
  /**
   * Quellfeld der Zuständigkeit – bei kind='assignable' ein Personen-Feld
   * (widget='user'), bei kind='group_from_field' ein Gruppen-Feld
   * (widget='group'). Serverseitig in beiden Fällen Pflicht.
   */
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
  /** Bei type='assign_sequence': Name des Nummernkreises (Pflicht, wie `field`). */
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
export interface LayoutNoteItem { type: 'note'; text: string; tone: NoteTone; width: LayoutWidth; visibleWhen?: Condition | null }
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

/**
 * Was bei `onReject` passiert: den Auftrag ablehnen oder auf eine FRÜHERE Phase
 * zur Nachbesserung zurückgeben. Wire-Form: 'reject' | `back_to:<phasen_key>`.
 */
export type ApprovalOnReject = 'reject' | `back_to:${string}`

/**
 * Eine Freigabe-Phase: eine Frage, zwei Antworten. Pflicht bei kind='approval',
 * serverseitig verboten bei jeder anderen Phasenart.
 *
 * `externalLink` ist der Grund für den Phasentyp: die entscheidende Person
 * arbeitet nicht zwingend im System. Der Mail-Link führt auf eine
 * Bestätigungsseite, entschieden wird per POST.
 */
export interface ApprovalSpec {
  question: string
  approveLabel: string
  rejectLabel: string
  /** Mail mit Entscheidungs-Link versenden? Ohne das läuft die Freigabe nur in der App. */
  externalLink: boolean
  /** Freitext-Vorlage für den Mail-Text. Platzhalter `{{feld.key}}` (plus
   *  {{title}}, {{id}}) werden aus den Auftragswerten ersetzt. `null` = nur die
   *  Frage steht in der Mail. */
  emailBody: string | null
  /** Gültigkeit des Links als ISO-8601-Dauer (Default 'P7D'). */
  linkMaxAge: string
  /** Begründung bei Ablehnung verlangen. */
  requireReason: boolean
  /** Feld, in das die rohe Entscheidung ('approve'/'reject') geschrieben wird. */
  decisionField: string | null
  /** Feld, in das die Begründung geschrieben wird (dann greift die Sichtbarkeit). */
  reasonField: string | null
  onReject: ApprovalOnReject
}

/** Vorlage einer Dokument-Phase (view='document'): HTML mit `{{feld.key}}`-
 *  Platzhaltern (plus {{title}}, {{id}}), zur Laufzeit vorausgefüllt, im Editor
 *  anpassbar und als Word/PDF exportierbar. */
export interface DocumentSpec {
  templateHtml: string
  filename: string
  title: string
  /** Marker→Feld-Zuordnung für eine hochgeladene .docx-Vorlage: {{marker}} wird
   *  beim Export durch den Wert des Felds ersetzt; nicht zugeordnete Marker
   *  bleiben als Lücke. */
  bindings: Record<string, string>
}

export interface PhaseDef {
  key: string
  label: string | null
  kind: PhaseKind
  view: PhaseView
  enterStatus: string | null
  grantsFullView: boolean
  responsibility: Responsibility
  /** Pflicht bei kind='approval', sonst `null` (der Server lehnt ihn sonst ab). */
  approval: ApprovalSpec | null
  /** Pflicht bei view='document', sonst `null`. */
  document: DocumentSpec | null
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
  /** Darf der Auftrags-Titel NACH dem Anlegen noch geändert werden? false =
   *  beim Anlegen festgelegt, danach überall nur lesbar (der Server weist
   *  Änderungen mit TITLE_LOCKED ab). */
  titleEditable: boolean
  /** Optionale Titel-Vorlage mit {{feld.key}} (Startphasen-Werte) und
   *  {{erstellt}} (Erstellzeitpunkt). Gesetzt → der Titel wird beim Anlegen
   *  daraus erzeugt statt manuell eingegeben. */
  titleTemplate: string | null
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
  /**
   * System-Prozess: gehört zum Produkt, entsteht beim Start automatisch und ist
   * nicht änderbar (Server: 403 `SYSTEM_PROCESS_READONLY`). Der Server leitet
   * das aus dem Schlüssel ab, es gibt kein DB-Feld dafür. Optional, weil ein
   * älteres Backend das Merkmal nicht mitschickt – siehe lib/processSystem.ts.
   */
  is_system?: boolean | null
  /** Global deaktiviert? Dann lassen sich keine neuen Aufträge anlegen. Key-weit
   *  (unabhängig von der Version); im Katalog und in der veröffentlichten Ansicht
   *  gefüllt. Fehlt das Feld (älteres Backend), gilt der Prozess als aktiv. */
  disabled?: boolean | null
  /** Nur im Katalog (GET /processes): darf DIESE Person hier anlegen? */
  may_create?: boolean | null
  /** Nur im Katalog: Symbol aus der Definition (die selbst nicht mitkommt). */
  icon?: string | null
  /** Nur im Katalog: Kurzbeschreibung aus der Definition. */
  description?: string | null
}

/** Eine Version im Lösch-Umfang. */
export interface ProcessDeleteVersion {
  version: number
  status: string
  rev: number | null
  tickets: number
}

/** Antwort auf das Anfordern einer Löschung – es ist noch NICHTS gelöscht. */
export interface ProcessDeleteRequestOut {
  key: string
  name: string
  versions: ProcessDeleteVersion[]
  tickets: number
  /** Adresse, an die die Bestätigungs-Mail ging (ADMIN_MAIL). */
  recipient: string
  expires_at: string
}

/** Was der Bestätigungs-Link löschen würde. */
export interface ProcessDeletePreview {
  key: string
  name: string
  versions: ProcessDeleteVersion[]
  tickets: number
  with_tickets: boolean
  requested_by: string | null
}

/** Welche Felder beim ANLEGEN sichtbar/ausfüllbar sind (GET /processes/{key}/field-access). */
export interface FieldAccess {
  visible_fields: string[]
  editable_fields: string[]
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

/**
 * Vom Server AUFGELÖSTE Zuständigkeit. Achtung: 'assignable' und
 * 'group_from_field' erscheinen hier nicht – sie lösen sich zu 'user' bzw.
 * 'group' auf (mit `from_field`/`assignable` als Zusatzinfo), damit Mailversand
 * und Rechte unverändert greifen.
 */
export type ResolvedResponsibility =
  | { kind: 'departments'; departments: { group: string; required: boolean; status: string }[] }
  //: `group`/`user` sind NULL, wenn die Zuständigkeit aus einem Feld kommt und
  //: dieses Feld (noch) leer ist – dann ist NIEMAND zuständig. Das muss die
  //: Oberfläche zeigen können, statt an einem leeren String zu scheitern.
  | { kind: 'group'; group: string | null; from_field?: string | null; assignable?: boolean }
  | { kind: 'user'; user: string | null; from_field?: string | null; assignable?: boolean }
  | { kind: 'owner' }
  | { kind: 'unknown' }

/**
 * Was die angemeldete Person mit DIESEM Auftrag darf – kommt vom Server.
 * Nicht nachbauen: das Frontend kennt die Gruppen-Mitgliedschaft nicht.
 */
export interface TicketAbilities {
  edit: boolean
  internal_comment: boolean
  manage_watchers: boolean
  /** Dateien hochladen – weiter gefasst als edit: auch die Ersteller:in darf
   *  Unterlagen nachreichen, solange der Auftrag läuft. */
  attach: boolean
  reopen: boolean
  /** Notfalleingriffe (Admin): hängenden Auftrag zwangsweise abschließen bzw. löschen. */
  archive: boolean
  delete: boolean
}

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
  abilities?: TicketAbilities
  /**
   * Welche Felder diese Person SEHEN bzw. in der aktuellen Phase BEARBEITEN darf.
   * Kommt vom Server – das Frontend kennt die Gruppen-Mitgliedschaft nicht und
   * könnte die Entscheidung nicht nachbauen.
   */
  visible_fields?: string[]
  editable_fields?: string[]
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
