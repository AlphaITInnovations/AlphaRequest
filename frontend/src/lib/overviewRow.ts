/**
 * Eine Zeile der Übersicht in ANZEIGBARER Form.
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist – das
 * Projekt hat kein jsdom.
 *
 * Der Listen-Endpunkt liefert IDs, keine Namen: `process_key` statt Prozessname,
 * `responsibility` mit Gruppen-/Personen-IDs. Die Namen kommen aus dem Katalog
 * (`GET /processes`) und den Auswahl-Quellen (lib/processSources.ts) und werden
 * hier als Nachschlage-Funktionen hereingegeben. Fehlt ein Name, steht der
 * ROHWERT da – eine erfundene Beschriftung wäre eine Falschaussage über den
 * echten Stand.
 *
 * Priorität ist bewusst NICHT Teil der Zeile: sie ist überall ausgeblendet, bis
 * geklärt ist, wie sie sinnvoll genutzt wird (Feld bleibt in DB und API).
 */
import { describeResponsibility, type ResponsibilityIn } from '@/lib/processResponsibility'
import { STATUS_LABEL } from '@/lib/processSchema'

export interface OverviewTicketIn {
  id: number
  title?: string | null
  process_key?: string | null
  status?: string | null
  current_phase_label?: string | null
  owner_id?: string | null
  owner_name?: string | null
  created_at?: string | null
  updated_at?: string | null
  responsibility?: ResponsibilityIn | null
}

export interface OverviewRowLookup {
  /** Prozess-Key → Anzeigename (aus dem Katalog). */
  processName?: (key: string) => string | undefined
  /** Prozess-Key → Symbol (aus dem Katalog). */
  processIcon?: (key: string) => string | undefined
  /** Gruppen-ID → Name der Fachabteilung. */
  groupName?: (id: string) => string
  /** Personen-ID → Anzeigename. */
  userName?: (id: string) => string
}

export interface OverviewResponsible {
  /** Anzeigename der zuständigen Stelle; leer genau dann, wenn `missing`. */
  text: string
  /** Art der Stelle, z. B. „Fachabteilung". */
  role: string
  /** Niemand zuständig – der Auftrag bleibt liegen. */
  missing: boolean
  /** Klartext, WARUM niemand zuständig ist. */
  hint: string
}

export interface OverviewRow {
  id: number
  title: string
  processKey: string
  /** Name aus dem Katalog, sonst der Key (roh). */
  processLabel: string
  processIcon: string
  status: string
  statusLabel: string
  phaseLabel: string
  ownerName: string
  responsible: OverviewResponsible
  createdAt: string
  updatedAt: string
}

/** Platzhalter für „nicht gesetzt" – überall derselbe, damit Spalten ruhig bleiben. */
export const LEER = '—'

/**
 * Zeitstempel deutsch. Der Server schickt naive UTC-Werte (kein „Z"); ohne die
 * Ergänzung würde der Browser sie als Ortszeit lesen und die Anzeige läge je
 * nach Zeitzone daneben. Ein unlesbarer Wert wird ROH ausgegeben, nie geraten.
 */
export function formatDateTime(ts?: string | null): string {
  if (!ts) return LEER
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`
  const d = new Date(s)
  if (isNaN(d.getTime())) return ts
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function toOverviewRow(t: OverviewTicketIn, look: OverviewRowLookup = {}): OverviewRow {
  const key = String(t.process_key ?? '')
  const status = String(t.status ?? '')
  const resp = describeResponsibility(t.responsibility, {
    groupName: look.groupName,
    userName: look.userName,
    ownerName: t.owner_name,
  })
  return {
    id: t.id,
    title: (t.title || '').trim() || `Auftrag #${t.id}`,
    processKey: key,
    processLabel: look.processName?.(key)?.trim() || key || LEER,
    processIcon: look.processIcon?.(key)?.trim() || '',
    status,
    statusLabel: STATUS_LABEL[status] ?? (status || LEER),
    phaseLabel: (t.current_phase_label || '').trim() || LEER,
    ownerName: (t.owner_name || '').trim() || LEER,
    responsible: {
      text: resp.missing ? '' : resp.name,
      role: resp.roleLabel,
      missing: resp.missing,
      hint: resp.missingHint,
    },
    createdAt: formatDateTime(t.created_at),
    updatedAt: formatDateTime(t.updated_at),
  }
}

export function toOverviewRows(
  tickets: readonly OverviewTicketIn[], look: OverviewRowLookup = {},
): OverviewRow[] {
  return tickets.map((t) => toOverviewRow(t, look))
}

/**
 * Nachschlage-Funktionen aus den geladenen Listen bauen. Solange eine Liste noch
 * nicht da ist (oder nicht geladen werden konnte), bleibt der Rohwert stehen –
 * die Übersicht wartet nicht auf die Namen.
 */
export function buildLookup(opts: {
  catalog?: readonly { key: string; name?: string | null; icon?: string | null }[]
  groups?: readonly { id: string; name?: string | null }[]
  users?: readonly { id: string; displayName?: string | null }[]
}): OverviewRowLookup {
  const prozesse = new Map((opts.catalog ?? []).map((p) => [p.key, p]))
  const gruppen = new Map((opts.groups ?? []).map((g) => [g.id, g.name || g.id]))
  const personen = new Map((opts.users ?? []).map((u) => [u.id, u.displayName || u.id]))
  return {
    processName: (k) => prozesse.get(k)?.name ?? undefined,
    processIcon: (k) => prozesse.get(k)?.icon ?? undefined,
    groupName: (id) => gruppen.get(id) ?? id,
    userName: (id) => personen.get(id) ?? id,
  }
}
