/**
 * „Phase X von Y" samt Phasen-Namen für die Detailansicht eines Prozess-Auftrags.
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist – das
 * Projekt hat kein jsdom.
 *
 * ZWEI QUELLEN, EINE ANZEIGE: die NAMEN der Phasen stehen in der gepinnten
 * Definition, wie weit der Auftrag ist steht in `runtime.current_index`.
 *
 * Der Index darf `phases.length` ERREICHEN – so beendet die Laufzeit einen
 * Auftrag (`process_runtime`: current_index == len(phases) heißt „durch").
 * Genau dieser Fall darf nicht als „Phase 5 von 4" erscheinen, deshalb wird die
 * Anzeige-Nummer gekappt und `finished` gesetzt.
 */

/** Nur was für die Anzeige gebraucht wird – `PhaseDef` erfüllt das strukturell. */
export interface PhaseStepInput {
  key: string
  label?: string | null
}

/**
 * `stopped` gibt es, weil ein abgelehnter Auftrag nicht „aktuell" in einer Phase
 * steht: dort arbeitet niemand mehr. Grün/„Aktuell" wäre an der Stelle eine Lüge.
 */
export type PhaseStepStatus = 'done' | 'current' | 'stopped' | 'pending'

export interface PhaseStep {
  key: string
  /** Sprechender Name; fällt auf den Schlüssel zurück und ist damit nie leer. */
  label: string
  status: PhaseStepStatus
  /** 1-basierte Nummer für die Anzeige. */
  number: number
}

const STATUS_LABEL: Record<PhaseStepStatus, string> = {
  done: 'Erledigt',
  current: 'Aktuell',
  stopped: 'Hier gestoppt',
  pending: 'Ausstehend',
}

export function phaseStepLabel(status: PhaseStepStatus): string {
  return STATUS_LABEL[status]
}

export interface PhaseProgressOptions {
  /** Auftrag abgelehnt (`runtime.rejected`): die erreichte Phase steht still. */
  rejected?: boolean
}

export interface PhaseProgressView {
  steps: PhaseStep[]
  total: number
  /** 1-basierte Nummer für „Phase X von Y"; 0 nur, wenn es keine Phasen gibt. */
  position: number
  /** Alle Phasen durchlaufen (current_index >= Anzahl Phasen). */
  finished: boolean
  rejected: boolean
  /** Kurzfassung für die Plakette, z. B. „Phase 2 von 4". */
  text: string
}

function stepStatus(
  i: number, current: number, rejected: boolean,
): PhaseStepStatus {
  if (i < current) return 'done'
  if (i > current) return 'pending'
  return rejected ? 'stopped' : 'current'
}

export function phaseProgress(
  phases: readonly PhaseStepInput[] | null | undefined,
  currentIndex: number | null | undefined,
  opts: PhaseProgressOptions = {},
): PhaseProgressView {
  const list = (phases ?? []).filter((p): p is PhaseStepInput => !!p && !!p.key)
  const total = list.length
  // Ein kaputter Index darf die Anzeige nicht kippen: alles Unbrauchbare wird 0.
  const raw = Number(currentIndex)
  const current = Number.isFinite(raw) ? Math.max(0, Math.trunc(raw)) : 0
  const finished = total > 0 && current >= total
  const rejected = !!opts.rejected
  const position = total === 0 ? 0 : Math.min(current + 1, total)

  const steps: PhaseStep[] = list.map((p, i) => ({
    key: p.key,
    label: p.label || p.key,
    number: i + 1,
    status: stepStatus(i, current, rejected),
  }))

  return { steps, total, position, finished, rejected, text: progressText(total, position, finished, rejected) }
}

function progressText(
  total: number, position: number, finished: boolean, rejected: boolean,
): string {
  // Ohne Phasen gibt es nichts zu zählen – eine erfundene „Phase 1 von 0" wäre
  // schlimmer als der ehrliche Hinweis.
  if (total === 0) return 'Keine Phasen hinterlegt'
  if (rejected) return `Abgelehnt in Phase ${position} von ${total}`
  if (finished) return total === 1 ? 'Phase durchlaufen' : `Alle ${total} Phasen durchlaufen`
  return `Phase ${position} von ${total}`
}
