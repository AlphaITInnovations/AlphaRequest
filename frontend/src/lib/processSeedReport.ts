/**
 * Aufbereitung des Berichts von `POST /processes:seed` für die Oberfläche.
 *
 * WARUM EIN EIGENES MODUL: der Bericht ist die einzige Rückmeldung des
 * Einspielens – und der Trockenlauf ist der ganze Sinn der Sache. Was er sagt,
 * muss also stimmen. Im Projekt gibt es kein jsdom/@vue/test-utils, deshalb
 * liegt die Auswertung hier als reine Funktion und wird getestet; die .vue-Datei
 * malt nur noch.
 *
 * ZÄHLUNG AUS DEN ZEILEN, NICHT AUS DEN SERVER-SUMMEN: der Bericht führt beides,
 * und eine Kopfzeile, die der Liste darunter widerspricht („9 angelegt“ über
 * zehn Einträgen „übersprungen“), wäre schlimmer als eine fehlende Kopfzeile.
 *
 * FELDNAMEN: kanonisch ist snake_case wie im übrigen API (`create_permissions`).
 * Weil der Bericht serverseitig aus einem Dataclass mit DEUTSCHEN Feldnamen
 * entsteht (services/seed_definitions.py: `aktion`, `meldung`, …), werden diese
 * Namen ebenfalls akzeptiert – ein direkt serialisiertes Dataclass darf nicht in
 * einer leeren Tabelle enden.
 */

export type SeedAction = 'created' | 'would_create' | 'skipped' | 'error'
export type SeedTone = 'ok' | 'info' | 'muted' | 'error'

const ACTIONS: readonly string[] = ['created', 'would_create', 'skipped', 'error']

const ACTION_LABEL: Record<SeedAction, string> = {
  created: 'angelegt',
  would_create: 'wird angelegt',
  skipped: 'übersprungen',
  error: 'Fehler',
}

const ACTION_TONE: Record<SeedAction, SeedTone> = {
  created: 'ok',
  would_create: 'info',
  skipped: 'muted',
  error: 'error',
}

/** Erstellrechte, die der Lauf aus dem Alt-System übernehmen würde. */
export interface SeedCreatePermissions {
  everyone: boolean
  groups: string[]
  users: string[]
}

/** Was mit EINEM mitgelieferten Prozess passiert (ist) – anzeigefertig. */
export interface SeedRow {
  /** Überschrift der Zeile: der Schlüssel, sonst der Dateiname. */
  title: string
  key: string | null
  file: string | null
  action: SeedAction
  label: string
  tone: SeedTone
  message: string
  warnings: string[]
  permissions: SeedCreatePermissions | null
  /** Alt-Gruppen, die `may_create` nie zu sehen bekommt (AD-Gruppen). */
  ineffectiveGroups: string[]
  /** System-Prozess: wird automatisch gepflegt, der Lauf lässt ihn liegen. */
  isSystem: boolean
}

export interface SeedCounts {
  /** created + would_create – „angelegt bzw. anzulegen“. */
  created: number
  skipped: number
  errors: number
  total: number
}

export interface SeedSummary {
  /** false = Trockenlauf, es wurde nichts geschrieben. */
  commit: boolean
  rows: SeedRow[]
  requiredGroups: string[]
  createdGroups: string[]
  missingGroups: string[]
  counts: SeedCounts
  headline: string
  /** Nichts anzulegen – Einspielen wäre ein Klick ohne Wirkung. */
  nothingToDo: boolean
  hasErrors: boolean
}

// ── Rohwerte einsammeln ──────────────────────────────────────────────────────

function obj(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** Erster vorhandener Wert unter mehreren Namen (snake_case zuerst). */
function pick(src: Record<string, unknown> | null, ...names: string[]): unknown {
  if (!src) return undefined
  for (const n of names) {
    if (src[n] !== undefined && src[n] !== null) return src[n]
  }
  return undefined
}

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** Textliste ohne Leerzeilen; Fremdtypen fliegen raus statt als „[object …]“. */
function strList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => (typeof v === 'string' ? v.trim() : '')).filter(Boolean)
}

function permissions(value: unknown): SeedCreatePermissions | null {
  const cp = obj(value)
  if (!cp) return null
  return {
    everyone: cp.everyone === true,
    groups: strList(cp.groups),
    users: strList(cp.users),
  }
}

function row(value: unknown): SeedRow | null {
  const o = obj(value)
  if (!o) return null
  const key = str(pick(o, 'key')) || null
  const file = str(pick(o, 'file', 'datei')) || null
  const raw = str(pick(o, 'action', 'aktion'))
  const known = ACTIONS.includes(raw)
  // Unbekannte Aktion als Fehler führen: lieber auffällig falsch als still
  // durchgewinkt – der Lauf schreibt in die Datenbank.
  const action: SeedAction = known ? (raw as SeedAction) : 'error'
  return {
    title: key || file || '(ohne Schlüssel)',
    key,
    file,
    action,
    label: known ? ACTION_LABEL[action] : `unbekannt (${raw || '—'})`,
    tone: ACTION_TONE[action],
    message: str(pick(o, 'message', 'meldung')),
    warnings: strList(pick(o, 'warnings', 'warnungen')),
    permissions: permissions(pick(o, 'create_permissions', 'createPermissions')),
    ineffectiveGroups: strList(pick(o, 'ineffective_groups', 'wirkungslose_gruppen')),
    isSystem: pick(o, 'is_system', 'system') === true,
  }
}

// ── Öffentliche Auswertung ───────────────────────────────────────────────────

/**
 * Kopfzeile des Berichts. Nennt beim Trockenlauf ausdrücklich, dass nichts
 * geschrieben wurde – sonst liest sich „9 angelegt“ wie eine erledigte Sache.
 */
export function seedHeadline(commit: boolean, counts: SeedCounts): string {
  const teile = [
    commit ? `${counts.created} angelegt` : `${counts.created} würden angelegt`,
    `${counts.skipped} übersprungen`,
  ]
  if (counts.errors) teile.push(counts.errors === 1 ? '1 Fehler' : `${counts.errors} Fehler`)
  const kopf = commit ? 'Eingespielt' : 'Trockenlauf – es wurde nichts geschrieben'
  return `${kopf}: ${teile.join(', ')}.`
}

/** Kurzfassung der Erstellrechte, wie sie in der Zeile steht. */
export function permissionsSummary(cp: SeedCreatePermissions | null): string | null {
  if (!cp) return null
  const teile: string[] = []
  if (cp.everyone) teile.push('alle Angemeldeten')
  if (cp.groups.length) {
    teile.push(cp.groups.length === 1 ? '1 Fachabteilung' : `${cp.groups.length} Fachabteilungen`)
  }
  if (cp.users.length) {
    teile.push(cp.users.length === 1 ? '1 Person' : `${cp.users.length} Personen`)
  }
  // Leere Rechte sind kein Fehler: ohne Alt-Daten bleibt es beim Admin-Fallback.
  return teile.length ? teile.join(' · ') : 'nur Admins'
}

/** Rohbericht → anzeigefertige Zusammenfassung. Wirft nicht, auch bei Müll. */
export function normalizeSeedReport(raw: unknown): SeedSummary {
  // Antwort mit und ohne data-Hülle akzeptieren (der API-Client wickelt aus,
  // aber ein Bericht aus einer anderen Quelle soll auch lesbar sein).
  let src = obj(raw)
  if (src && !pick(src, 'outcomes') && obj(src.data)) src = obj(src.data)

  const rows = (Array.isArray(pick(src, 'outcomes')) ? (pick(src, 'outcomes') as unknown[]) : [])
    .map(row)
    .filter((r): r is SeedRow => r !== null)

  const counts: SeedCounts = {
    created: rows.filter((r) => r.action === 'created' || r.action === 'would_create').length,
    skipped: rows.filter((r) => r.action === 'skipped').length,
    errors: rows.filter((r) => r.action === 'error').length,
    total: rows.length,
  }
  const commit = pick(src, 'commit') === true

  return {
    commit,
    rows,
    requiredGroups: strList(pick(src, 'required_groups', 'pflichtgruppen')),
    createdGroups: strList(pick(src, 'created_groups', 'angelegte_gruppen')),
    missingGroups: strList(pick(src, 'missing_groups', 'fehlende_gruppen')),
    counts,
    headline: seedHeadline(commit, counts),
    nothingToDo: counts.created === 0,
    hasErrors: counts.errors > 0,
  }
}
