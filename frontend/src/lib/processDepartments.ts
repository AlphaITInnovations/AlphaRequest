/**
 * Fachabteilungs-Stand eines Prozess-Auftrags: Beschriftungen, Fortschritt und
 * die Arbeitslisten-Frage „wartet dieser Auftrag noch auf MEINE Abteilung?".
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist – das
 * Projekt hat kein jsdom.
 *
 * Der Stand kommt aus `ticket.responsibility.departments` und ist der LIVE-Stand
 * der aktuellen Phase (backend/api/v1/process_tickets._out setzt dafür
 * `process_runtime.current_departments` ein). `types/process.ts` beschreibt dort
 * nur die drei Pflichtangaben; wer wann mit welcher Notiz quittiert hat
 * (`by`, `by_name`, `at`, `note`) schreibt
 * `process_runtime.set_department_status` zusätzlich hinein. Diese Felder sind
 * hier deshalb OPTIONAL ergänzt, statt die geteilte Typdatei anzufassen.
 *
 * Die Regeln spiegeln absichtlich 1:1 das Backend:
 *  - „skipped" (nicht zuständig) gilt als erledigt,
 *  - `required` fehlt → Pflicht (Default der DepartmentRule ist true),
 *  - unbekannter Status gilt als offen und wird ROH angezeigt, nie geraten.
 */

// ── Datenform ─────────────────────────────────────────────────────────────────

/** Bekannte Wire-Werte. Der Server darf mehr liefern – siehe `status: string`. */
export type DepartmentStatus = 'open' | 'done' | 'skipped' | 'rejected'

export interface DepartmentState {
  group: string
  /** Fehlt der Wert, gilt Pflicht (Default der Definition). */
  required?: boolean
  /** Absichtlich `string`: ein unbekannter Status darf nicht zum Typfehler werden. */
  status?: string | null
  by?: string | null
  by_name?: string | null
  at?: string | null
  note?: string | null
}

/**
 * Schmale Sicht auf einen Auftrag – nur was die Arbeitslisten-Frage braucht.
 * `ProcessTicketOut` erfüllt das strukturell, ebenso ein Listen-Eintrag.
 * `group` trägt die EINFACHE Gruppen-Zuständigkeit (kind='group'; auch
 * group_from_field liefert der Server so aus, z. B. das Basis-Ticket).
 */
export interface DepartmentAwareTicket {
  status?: string | null
  runtime?: { rejected?: boolean } | null
  responsibility?: {
    kind: string
    group?: string | null
    departments?: DepartmentState[]
  } | null
}

// ── Beschriftung ──────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  open: 'Offen',
  done: 'Erledigt',
  skipped: 'Nicht zuständig',
  rejected: 'Abgelehnt',
}

/**
 * Beschriftung eines Abteilungs-Status. Ein unbekannter Status wird als Rohwert
 * gezeigt – eine erfundene Beschriftung wäre eine Lüge über den echten Stand.
 * Fehlt der Status ganz, gilt er als offen (so wertet ihn auch das Backend).
 */
export function departmentStatusLabel(status?: string | null): string {
  if (!status) return STATUS_LABEL.open
  return STATUS_LABEL[status] ?? status
}

/** Optische Einordnung (Farbe der Status-Plakette). */
export type DepartmentTone = 'open' | 'done' | 'skipped' | 'rejected' | 'unknown'

export function departmentTone(status?: string | null): DepartmentTone {
  if (!status) return 'open'
  if (status === 'open' || status === 'done' || status === 'skipped' || status === 'rejected') {
    return status
  }
  // Unbekannt bleibt neutral: grün für etwas, das wir nicht kennen, wäre falsch.
  return 'unknown'
}

/** Pflicht/optional als Text – „optional" muss auf einen Blick erkennbar sein. */
export function requiredLabel(required?: boolean): string {
  return required === false ? 'Optional' : 'Pflicht'
}

// ── Einzelner Eintrag ─────────────────────────────────────────────────────────

/** Fehlender Wert = Pflicht (Default der DepartmentRule im Backend). */
export function isRequired(dept: DepartmentState): boolean {
  return dept.required !== false
}

/**
 * Ist der Teil dieser Abteilung erledigt? „skipped" zählt ausdrücklich mit:
 * „nicht zuständig / nichts zu tun" beendet die Aufgabe genauso wie „erledigt".
 */
export function isDepartmentSettled(status?: string | null): boolean {
  return status === 'done' || status === 'skipped'
}

/**
 * Wartet diese Abteilung noch auf eine Quittierung?
 *
 * „rejected" ist NICHT offen: mit der Ablehnung ist der ganze Auftrag beendet,
 * da wartet niemand mehr.
 */
export function isDepartmentPending(dept: DepartmentState): boolean {
  return !isDepartmentSettled(dept.status) && dept.status !== 'rejected'
}

// ── Fortschritt ───────────────────────────────────────────────────────────────

/**
 * Pflicht-Abteilungen, die den Phasenabschluss blockieren – exakter Spiegel von
 * `process_runtime.open_required_departments` (dort zählt auch „rejected" als
 * offen; praktisch belanglos, weil der Auftrag dann terminal ist).
 */
export function blockingDepartments(depts: readonly DepartmentState[] | null | undefined)
  : DepartmentState[] {
  return (depts ?? []).filter((d) => !!d && isRequired(d) && !isDepartmentSettled(d.status))
}

export interface DepartmentProgress {
  total: number
  /** done + skipped. */
  settled: number
  /** Weder quittiert noch abgelehnt. */
  open: number
  required: number
  /** Pflicht-Abteilungen, die `:advance` noch blockieren. */
  openRequired: number
  rejected: number
  /** Keine Pflicht-Abteilung mehr offen → das Weiterschalten ist frei. */
  ready: boolean
  /** Kopfzeile, z. B. „2 von 3 erledigt". */
  text: string
}

export function departmentProgress(depts: readonly DepartmentState[] | null | undefined)
  : DepartmentProgress {
  const list = (depts ?? []).filter((d): d is DepartmentState => !!d)
  const settled = list.filter((d) => isDepartmentSettled(d.status)).length
  const rejected = list.filter((d) => d.status === 'rejected').length
  const openRequired = blockingDepartments(list).length
  return {
    total: list.length,
    settled,
    open: list.filter(isDepartmentPending).length,
    required: list.filter(isRequired).length,
    openRequired,
    rejected,
    ready: openRequired === 0,
    text: list.length ? `${settled} von ${list.length} erledigt`
                      : 'Keine Fachabteilungen beteiligt',
  }
}

// ── Arbeitsliste: „wartet auf meine Abteilung" ───────────────────────────────

/** Spiegel von `backend/api/v1/process_tickets._is_terminal`. */
const TERMINAL_STATUS = new Set(['archived', 'rejected'])

export function isTicketTerminal(ticket: DepartmentAwareTicket): boolean {
  return TERMINAL_STATUS.has(String(ticket?.status ?? '')) || !!ticket?.runtime?.rejected
}

export interface AwaitOptions {
  /**
   * Nur Abteilungen zählen, deren Quittierung den Auftrag BLOCKIERT.
   * Standard `false`: auch eine optionale Abteilung ist beteiligt und soll in
   * der Arbeitsliste auftauchen – sonst übersieht sie ihren Teil.
   */
  requiredOnly?: boolean
}

/**
 * Wartet dieser Auftrag noch auf die Abteilung `groupId`?
 *
 * Zwei Zuständigkeits-Formen zählen:
 *  - kind='departments': die Abteilung muss noch quittieren (Pending-Regeln oben),
 *  - kind='group': der Auftrag LIEGT bei genau dieser Abteilung (so liefert der
 *    Server auch group_from_field aus – z. B. das Basis-Ticket). Eine einfache
 *    Gruppen-Zuständigkeit blockiert immer, `requiredOnly` ändert daran nichts.
 *
 * Nur die AKTUELLE Phase zählt: `responsibility` beschreibt ausschließlich sie.
 * Terminale Aufträge (abgelehnt/archiviert) warten nie.
 */
export function awaitsDepartment(
  ticket: DepartmentAwareTicket | null | undefined,
  groupId: string,
  opts: AwaitOptions = {},
): boolean {
  if (!ticket || !groupId) return false
  if (isTicketTerminal(ticket)) return false
  const resp = ticket.responsibility
  if (!resp) return false
  if (resp.kind === 'group') return resp.group === groupId
  if (resp.kind !== 'departments') return false
  return (resp.departments ?? []).some((d) =>
    !!d && d.group === groupId && isDepartmentPending(d)
    && (!opts.requiredOnly || isRequired(d)))
}

/** Wie `awaitsDepartment`, aber für mehrere eigene Gruppen (Mehrfach-Mitgliedschaft). */
export function awaitsAnyDepartment(
  ticket: DepartmentAwareTicket | null | undefined,
  groupIds: readonly string[] | null | undefined,
  opts: AwaitOptions = {},
): boolean {
  return (groupIds ?? []).some((g) => awaitsDepartment(ticket, g, opts))
}

/** Aufträge, die auf `groupId` warten – Reihenfolge der Eingabe bleibt erhalten. */
export function ticketsAwaitingDepartment<T extends DepartmentAwareTicket>(
  tickets: readonly T[] | null | undefined,
  groupId: string,
  opts: AwaitOptions = {},
): T[] {
  return (tickets ?? []).filter((t) => awaitsDepartment(t, groupId, opts))
}

/** Dasselbe für mehrere eigene Gruppen; jeder Auftrag erscheint höchstens einmal. */
export function ticketsAwaitingAnyDepartment<T extends DepartmentAwareTicket>(
  tickets: readonly T[] | null | undefined,
  groupIds: readonly string[] | null | undefined,
  opts: AwaitOptions = {},
): T[] {
  return (tickets ?? []).filter((t) => awaitsAnyDepartment(t, groupIds, opts))
}
