/**
 * Abfrage-Plan und clientseitige Nachbearbeitung für die Übersicht (Startseite).
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist – das
 * Projekt hat kein jsdom.
 *
 * WARUM EIN „PLAN"?
 * `GET /process-tickets` kann `status` (GENAU EINEN), `process_key`, `q` (sucht
 * nur im Titel), `limit` und `offset`; sortiert wird immer nach `updated_at DESC`
 * (backend/database/process_tickets.list_tickets). Alles andere kann nur der
 * Client: mehrere Status gleichzeitig, die Arbeitslisten („wartet auf mich" /
 * „auf meine Abteilung") und jede andere Sortierung.
 *
 * Sobald etwas clientseitig passiert, ist die Liste NICHT mehr das
 * Gesamtergebnis, sondern nur das geladene Fenster – die neuesten `scanLimit`
 * Aufträge. Genau diese Unterscheidung trifft `planQuery`:
 *   `mode: 'server'` → serverseitig gefiltert und geblättert, vollständig,
 *   `mode: 'scan'`   → Fenster + `clientSide`-Begründungen, die die Oberfläche
 *                      ehrlich anzeigen MUSS (`isWindowTruncated`).
 *
 * Priorität kommt hier absichtlich NICHT vor (kein Filter, keine Sortierung):
 * sie ist überall ausgeblendet, bis geklärt ist, wie sie sinnvoll genutzt wird.
 * Feld und API bleiben unverändert.
 */
import {
  awaitsAnyDepartment, isTicketTerminal, type DepartmentState,
} from '@/lib/processDepartments'

// ── Status ────────────────────────────────────────────────────────────────────

/**
 * Status-Auswahl der Oberfläche in Anzeige-Reihenfolge – Spiegel von
 * `STATUS_LABEL` (lib/processSchema.ts) und damit des Backends. Ein Status, den
 * der Server künftig zusätzlich liefert, hat hier keinen Knopf; er wird trotzdem
 * angezeigt (siehe `statusAllowsEverything`), statt still zu verschwinden.
 */
export const OVERVIEW_STATUSES: readonly string[] = [
  'in_progress', 'in_request', 'waiting_contract', 'archived', 'rejected',
]

/** Startauswahl: alles AUSSER „Archiviert" – offene Aufträge im Fokus. */
export function defaultStatuses(): string[] {
  return OVERVIEW_STATUSES.filter((s) => s !== 'archived')
}

/** Die Auswahl schließt nichts aus → kein clientseitiger Filter nötig. */
export function statusAllowsEverything(statuses: readonly string[]): boolean {
  const set = new Set(statuses)
  return OVERVIEW_STATUSES.every((s) => set.has(s))
}

/** Genau EIN Status → der Server kann filtern (`?status=`), sonst undefined. */
export function statusServerParam(statuses: readonly string[]): string | undefined {
  const set = new Set(statuses)
  return set.size === 1 ? [...set][0] : undefined
}

/** Mehrere (oder keine) Status und nicht „alles" → muss der Client erledigen. */
export function statusNeedsClient(statuses: readonly string[]): boolean {
  if (statusAllowsEverything(statuses)) return false
  return new Set(statuses).size !== 1
}

/**
 * Clientseitiger Status-Filter. Deckt die Auswahl alle bekannten Status ab, wird
 * NICHT gefiltert – ein unbekannter Status (neuer Server, alte Oberfläche) soll
 * dann sichtbar bleiben und nicht stillschweigend herausfallen.
 */
export function filterByStatus<T extends { status?: string | null }>(
  rows: readonly T[], statuses: readonly string[],
): T[] {
  if (statusAllowsEverything(statuses)) return [...rows]
  const set = new Set(statuses)
  return rows.filter((r) => set.has(String(r.status ?? '')))
}

// ── Arbeitslisten (Sichten) ───────────────────────────────────────────────────

/**
 * Welcher Ausschnitt wird gezeigt? `all` ist die vollständige Liste (der Server
 * hat sie schon auf das Sichtbare begrenzt); die übrigen sind die Arbeitslisten,
 * die es vor dem Umbau als eigene Startseite gab.
 */
export type OverviewScope = 'all' | 'assigned' | 'departments' | 'created' | 'involved'

export const OVERVIEW_SCOPES: readonly OverviewScope[] = [
  'all', 'assigned', 'departments', 'created', 'involved',
]

export const SCOPE_LABEL: Record<OverviewScope, string> = {
  all: 'Alle Aufträge',
  assigned: 'Mir zugewiesen',
  departments: 'Meine Abteilungen',
  created: 'Von mir angelegt',
  involved: 'Beteiligt',
}

export const SCOPE_HINT: Record<OverviewScope, string> = {
  all: 'Alle Aufträge, die du sehen darfst – inklusive abgeschlossener.',
  assigned: 'Aufträge, deren aktuelle Phase dich persönlich als zuständig nennt.',
  departments: 'Aufträge, die auf eine Quittierung durch eine deiner Fachabteilungen warten.',
  created: 'Aufträge, die du selbst gestartet hast – auch abgeschlossene.',
  involved: 'Laufende Aufträge anderer, die du sehen darfst – als Zuständige:r, '
    + 'Beobachter:in oder mit Aufsichtsrecht.',
}

/** Text für die leere Liste – je Sicht eine andere Aussage. */
export const SCOPE_EMPTY: Record<OverviewScope, string> = {
  all: 'Keine Aufträge gefunden',
  assigned: 'Keine dir persönlich zugewiesenen Aufträge',
  departments: 'Keine Aufträge für deine Fachabteilungen',
  created: 'Du hast noch keinen Auftrag angelegt',
  involved: 'Keine laufenden Aufträge, an denen du beteiligt bist',
}

/**
 * Wer fragt? Ohne Personen-ID lässt sich keine der personenbezogenen Sichten
 * beantworten – dann bleiben sie LEER (default-deny), statt zu raten.
 */
export interface ScopeContext {
  userId: string | null
  /** Fachabteilungen, in denen diese Person Mitglied ist. */
  groupIds: readonly string[]
}

/**
 * Schmale Sicht auf einen Auftrag – nur was die Sichten brauchen.
 * `ProcessTicketOut` erfüllt das strukturell.
 */
export interface ScopeTicket {
  owner_id?: string | null
  status?: string | null
  runtime?: { rejected?: boolean } | null
  responsibility?: {
    kind: string
    user?: string | null
    departments?: DepartmentState[]
  } | null
}

/**
 * Gehört dieser Auftrag in die gewählte Sicht?
 *
 * `assigned`, `departments` und `involved` sind ARBEITSLISTEN: terminale
 * Aufträge (archiviert/abgelehnt) fallen heraus, dort wartet niemand mehr.
 * `created` ist bewusst KEINE Arbeitsliste, sondern „meine Aufträge" – dort
 * gehören abgeschlossene mit hinein, sonst wäre der eigene Vorgang nach dem
 * Abschluss nicht mehr auffindbar.
 */
export function inScope(t: ScopeTicket, scope: OverviewScope, ctx: ScopeContext): boolean {
  if (scope === 'all') return true
  const uid = ctx.userId
  if (!uid) return false
  if (scope === 'created') return t.owner_id === uid

  if (isTicketTerminal(t)) return false
  if (scope === 'involved') return t.owner_id !== uid
  if (scope === 'departments') return awaitsAnyDepartment(t, ctx.groupIds)

  // assigned: die aufgelöste Zuständigkeit nennt genau mich. `assignable` löst
  // der Server zu kind='user' auf, deshalb genügt dieser Fall; kind='owner'
  // zählt mit – als Ersteller:in am Zug zu sein ist auch Arbeit.
  const r = t.responsibility
  if (!r) return false
  if (r.kind === 'user') return r.user === uid
  if (r.kind === 'owner') return t.owner_id === uid
  return false
}

export function applyScope<T extends ScopeTicket>(
  rows: readonly T[], scope: OverviewScope, ctx: ScopeContext,
): T[] {
  return rows.filter((t) => inScope(t, scope, ctx))
}

// ── Sortierung ────────────────────────────────────────────────────────────────

export type OverviewSortKey = 'updated_at' | 'created_at' | 'id' | 'title' | 'owner' | 'status'
export type SortDir = 'asc' | 'desc'

/** Die EINZIGE Sortierung, die der Server selbst liefert (ORDER BY updated_at DESC). */
export const SERVER_SORT_KEY: OverviewSortKey = 'updated_at'
export const SERVER_SORT_DIR: SortDir = 'desc'

export function isServerOrder(key: OverviewSortKey, dir: SortDir): boolean {
  return key === SERVER_SORT_KEY && dir === SERVER_SORT_DIR
}

/**
 * Reihenfolge der Status beim Sortieren: von „hier passiert etwas" zu „fertig".
 * Ein unbekannter Status landet hinten, statt die Sortierung zu kippen.
 */
const STATUS_ORDER: Record<string, number> = {
  in_progress: 0, in_request: 1, waiting_contract: 2, archived: 3, rejected: 4,
}

/**
 * „Zuständig" fehlt in den Sortier-Schlüsseln mit Absicht: die Zuständigkeit
 * kommt als ID und wird erst über die nachgeladenen Namenslisten lesbar – eine
 * Sortierung darüber würde sich beim Nachladen unter der Hand umstellen.
 */
export interface SortableTicket {
  id: number
  title?: string | null
  owner_name?: string | null
  status?: string | null
  created_at?: string | null
  updated_at?: string | null
}

function sortValue(t: SortableTicket, key: OverviewSortKey): string | number {
  switch (key) {
    case 'id': return t.id
    case 'title': return String(t.title ?? '').toLowerCase()
    case 'owner': return String(t.owner_name ?? '').toLowerCase()
    case 'status': return STATUS_ORDER[String(t.status ?? '')] ?? 99
    case 'created_at': return String(t.created_at ?? '')
    default: return String(t.updated_at ?? '')
  }
}

/**
 * Sortiert eine Kopie. Bei Gleichstand bleibt die Reihenfolge des Servers
 * erhalten (Array.sort ist stabil) – zwei Aufträge mit gleichem Titel stehen
 * also weiter nach Änderungsdatum untereinander.
 */
export function sortTickets<T extends SortableTicket>(
  rows: readonly T[], key: OverviewSortKey, dir: SortDir,
): T[] {
  const richtung = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key)
    const vb = sortValue(b, key)
    if (va === vb) return 0
    return (va < vb ? -1 : 1) * richtung
  })
}

// ── Blätterung ────────────────────────────────────────────────────────────────

export function pageCount(rowCount: number, pageSize: number): number {
  if (pageSize <= 0) return 1
  return Math.max(1, Math.ceil(rowCount / pageSize))
}

/** Seite 1-basiert; außerhalb liegende Seiten liefern eine leere Liste. */
export function pageSlice<T>(rows: readonly T[], page: number, pageSize: number): T[] {
  const p = Math.max(1, Math.floor(page) || 1)
  return rows.slice((p - 1) * pageSize, p * pageSize)
}

// ── Plan ──────────────────────────────────────────────────────────────────────

/** Was der Server NICHT übernehmen kann – Begründung für die Ehrlichkeits-Zeile. */
export type ClientSideReason = 'status' | 'scope' | 'sort'

export const CLIENT_SIDE_LABEL: Record<ClientSideReason, string> = {
  status: 'mehrere Status gleichzeitig',
  scope: 'die Arbeitslisten-Sicht',
  sort: 'diese Sortierung',
}

export interface OverviewFilterState {
  scope: OverviewScope
  statuses: readonly string[]
  /** Freitext – der Server sucht damit NUR im Titel. */
  q: string
  processKey: string
  sortKey: OverviewSortKey
  sortDir: SortDir
}

export interface PlanOptions {
  /** 1-basiert. */
  page: number
  pageSize: number
  /** Obergrenze des Endpunkts (limit ≤ 200) – mehr gibt es nicht in einem Rutsch. */
  scanLimit: number
}

/** Genau die Parameter von `GET /process-tickets`. */
export interface QueryParams {
  status?: string
  process_key?: string
  q?: string
  limit: number
  offset: number
}

export interface QueryPlan {
  /** 'server' = vollständig geblättert · 'scan' = nur das geladene Fenster. */
  mode: 'server' | 'scan'
  params: QueryParams
  clientSide: ClientSideReason[]
}

export function planQuery(f: OverviewFilterState, o: PlanOptions): QueryPlan {
  const clientSide: ClientSideReason[] = []
  if (statusNeedsClient(f.statuses)) clientSide.push('status')
  if (f.scope !== 'all') clientSide.push('scope')
  if (!isServerOrder(f.sortKey, f.sortDir)) clientSide.push('sort')

  const mode: 'server' | 'scan' = clientSide.length ? 'scan' : 'server'
  const page = Math.max(1, Math.floor(o.page) || 1)
  const params: QueryParams = mode === 'server'
    ? { limit: o.pageSize, offset: (page - 1) * o.pageSize }
    // Im Scan-Modus blättert der Client im Fenster – der Server liefert immer
    // dessen Anfang, sonst fehlten die neuesten Aufträge in der Auswertung.
    : { limit: o.scanLimit, offset: 0 }

  const status = statusServerParam(f.statuses)
  if (status) params.status = status
  const key = f.processKey.trim()
  if (key) params.process_key = key
  const q = f.q.trim()
  if (q) params.q = q
  return { mode, params, clientSide }
}

/**
 * Ist das geladene Fenster kleiner als das Gesamtergebnis?
 *
 * `total` (meta.total) ist die Serverzahl für dieselben Server-Filter, vermindert
 * um die Zeilen, die im geladenen Fenster wegen fehlender Sichtbarkeit entfernt
 * wurden (backend/api/v1/process_tickets.list_process_tickets). Damit gilt genau
 * dann `total === loaded`, wenn der Server alles ausgeliefert hat – unabhängig
 * davon, wie viel unterwegs herausgefiltert wurde.
 *
 * Im Server-Modus ist `total > loaded` normal (es gibt weitere Seiten) und KEINE
 * Unvollständigkeit.
 */
export function isWindowTruncated(plan: QueryPlan, total: number, loaded: number): boolean {
  return plan.mode === 'scan' && total > loaded
}

/**
 * Auftragsnummer aus der Suche („#42", „42") – für den Direktsprung.
 *
 * Der Server sucht mit `q` ausschließlich im TITEL; eine Suche nach der Nummer
 * bliebe also ergebnislos. Statt einen unvollständigen Client-Filter zu bauen,
 * bietet die Oberfläche den Auftrag direkt zum Öffnen an.
 */
export function parseTicketRef(q: string): number | null {
  const m = /^#?(\d{1,12})$/.exec((q || '').trim())
  if (!m) return null
  const n = Number(m[1])
  return Number.isInteger(n) && n > 0 ? n : null
}
