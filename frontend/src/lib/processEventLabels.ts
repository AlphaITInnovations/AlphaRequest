/**
 * Beschriftung der Verlaufs-Einträge eines Prozess-Auftrags.
 *
 * Der Server liefert strukturierte Ereignisse (`action` + `details`), nicht
 * fertige Sätze – so bleibt der Verlauf maschinenlesbar und die Sprache liegt an
 * EINER Stelle. Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar
 * ist: das Projekt hat kein jsdom.
 *
 * Fällt eine Aktion durch (neuer Backend-Name, hier noch nicht bekannt), wird der
 * Rohwert gezeigt statt einer Lüge oder eines leeren Eintrags.
 */
import type { ProcessEvent } from '@/api/processEvents'

export type EventTone = 'neutral' | 'progress' | 'warn' | 'danger' | 'comment'

/** Wie ein Eintrag optisch eingeordnet wird (Farbe/Punkt in der Timeline). */
export function eventTone(ev: ProcessEvent): EventTone {
  switch (ev.action) {
    case 'comment': return 'comment'
    case 'advanced': return 'progress'
    case 'department_done': return 'progress'
    case 'created': return 'progress'
    case 'rejected':
    case 'department_rejected': return 'danger'
    case 'reopened':
    case 'approval_sent_back':
    case 'automation_fired': return 'warn'
    case 'approval_no_recipient': return 'danger'
    case 'approval_decided':
      return ev.details?.act === 'reject' ? 'danger' : 'progress'
    default: return 'neutral'
  }
}

export interface LabelCtx {
  /** Feld-Schlüssel → Beschriftung (aus der gepinnten Definition). */
  fieldLabels?: Record<string, string>
  /** Gruppen-ID → Name. */
  groupName?: (id: string) => string
  /** Phasen-Schlüssel → Beschriftung. */
  phaseLabels?: Record<string, string>
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

function feldListe(ev: ProcessEvent, ctx: LabelCtx): string {
  const raw = ev.details?.fields
  const keys = Array.isArray(raw) ? raw.filter((k): k is string => typeof k === 'string') : []
  const named = keys.map((k) => ctx.fieldLabels?.[k] || k)
  const hidden = num(ev.details?.fields_hidden)
  // Der Server sagt ehrlich, wie viele Felder ausgeblendet wurden – das hier zu
  // verschweigen würde den Eintrag falsch aussehen lassen.
  const rest = hidden ? ` (+${hidden} nicht sichtbar)` : ''
  return named.length ? `${named.join(', ')}${rest}` : rest.trim() || '—'
}

function phase(key: unknown, ctx: LabelCtx): string {
  const k = str(key)
  return k ? (ctx.phaseLabels?.[k] || k) : '—'
}

function gruppe(ev: ProcessEvent, ctx: LabelCtx): string {
  const g = str(ev.details?.group)
  if (!g) return '—'
  return ctx.groupName ? ctx.groupName(g) : g
}

const AUTOMATION_LABEL: Record<string, string> = {
  // „Benachrichtigung", nicht „Erinnerung": notify verschickt auch ERSTMALIGE
  // Mails (z. B. beim Weiterreichen des Basis-Tickets) – eine „Erinnerung" an
  // etwas, das man zum ersten Mal sieht, wäre eine Falschaussage.
  notify: 'Benachrichtigung',
  escalate: 'Eskalation',
  set_field: 'Feld gesetzt',
  set_priority: 'Priorität',
  set_status: 'Status',
  auto_advance: 'automatisch weitergeschaltet',
}

/** Einzeiler für einen Verlaufs-Eintrag. */
export function eventSummary(ev: ProcessEvent, ctx: LabelCtx = {}): string {
  switch (ev.action) {
    case 'created':
      return 'Auftrag angelegt'
    case 'updated':
      return `Angaben geändert: ${feldListe(ev, ctx)}`
    case 'advanced': {
      const from = phase(ev.details?.from_phase, ctx)
      const to = str(ev.details?.to_phase)
      if (!to) return `Phase „${from}“ abgeschlossen – Auftrag fertig`
      return `Phase „${from}“ abgeschlossen → „${phase(to, ctx)}“`
    }
    case 'rejected':
      return 'Auftrag abgelehnt'
    case 'reopened':
      return `Auftrag wieder aufgenommen (Phase „${phase(ev.details?.phase, ctx)}“)`
    case 'comment':
      return ev.internal ? 'Interner Nachtrag' : 'Nachtrag'
    case 'department_done':
      return `Fachabteilung abgeschlossen: ${gruppe(ev, ctx)}`
    case 'department_skipped':
      return `Fachabteilung übersprungen: ${gruppe(ev, ctx)}`
    case 'department_rejected':
      return `Ablehnung durch Fachabteilung: ${gruppe(ev, ctx)}`
    case 'watcher_added':
      return `Beobachter:in eingetragen: ${str(ev.details?.watcher_name)
        || str(ev.details?.watcher) || '—'}`
    case 'watcher_removed':
      return `Beobachtung beendet: ${str(ev.details?.watcher) || '—'}`
    case 'automation_fired': {
      // Der Anlass-Text der Automation (template) ist die ehrlichste
      // Beschriftung – erst ohne ihn fällt die Anzeige auf den Aktions-Typ zurück.
      const art = str(ev.details?.action)
      const anlass = str(ev.details?.template) || (art ? AUTOMATION_LABEL[art] || art : '')
      const id = str(ev.details?.automation)
      return `Automation ausgeführt${id ? `: ${id}` : ''}${anlass ? ` (${anlass})` : ''}`
    }
    case 'approval_decided': {
      const act = str(ev.details?.act)
      const wie = act === 'approve' ? 'freigegeben' : act === 'reject' ? 'abgelehnt' : 'entschieden'
      const via = str(ev.details?.via) === 'mail_link' ? ' (per Mail-Link)' : ''
      return `Freigabe: ${wie}${via}`
    }
    case 'approval_sent_back':
      return `Zur Nachbesserung zurückgegeben (Phase „${phase(ev.details?.phase, ctx)}“)`
    case 'approval_no_recipient':
      // Das ist ein BETRIEBSPROBLEM, kein Ablaufschritt: der Auftrag liegt still.
      return 'Freigabe-Mail konnte nicht zugestellt werden – keine Verteiler-Adresse hinterlegt'
    case 'priority_changed':
      return 'Priorität geändert'
    default:
      // Unbekannte Aktion ehrlich als Rohwert zeigen.
      return ev.action
  }
}

/** „vor 3 Minuten" / Datum – ohne Fremdbibliothek. */
export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const sek = Math.round((now.getTime() - d.getTime()) / 1000)
  if (sek < 0) return d.toLocaleString('de-DE')
  if (sek < 60) return 'gerade eben'
  if (sek < 3600) return `vor ${Math.floor(sek / 60)} Min.`
  if (sek < 86400) return `vor ${Math.floor(sek / 3600)} Std.`
  if (sek < 7 * 86400) return `vor ${Math.floor(sek / 86400)} Tag(en)`
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/** Absolute Anzeige für den Tooltip. */
export function absoluteTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('de-DE')
}
