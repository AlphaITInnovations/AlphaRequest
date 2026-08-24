/**
 * System-Prozesse in der Oberfläche.
 *
 * Ein System-Prozess gehört zum PRODUKT, nicht zur Konfiguration einer
 * Installation: er entsteht beim Start automatisch und wird bei Änderungen der
 * mitgelieferten Definition als NEUE Version nachgezogen. Deshalb ist er hier
 * nicht änderbar – und der Server erzwingt das ohnehin (403
 * `SYSTEM_PROCESS_READONLY`).
 *
 * WARUM KEINE SCHLÜSSEL-LISTE IM FRONTEND: welche Schlüssel System-Prozesse sind,
 * weiß nur der Server (`SYSTEM_PROCESS_KEYS` in services/seed_definitions.py) und
 * sagt es je Version mit `is_system`. Eine zweite Liste hier würde irgendwann
 * veralten und dann Knöpfe an einem Prozess ausblenden, der sehr wohl änderbar
 * ist. Fehlt das Merkmal (älteres Backend), sind die Knöpfe sichtbar und der
 * Server antwortet notfalls mit 403 – dafür gibt es `isSystemReadonlyError`.
 */
import { errorCode } from '@/lib/processErrors'
import type { ProcessIssue } from '@/types/process'

/** Fehlercode des Servers für jeden schreibenden Zugriff auf einen System-Prozess. */
export const SYSTEM_PROCESS_READONLY = 'SYSTEM_PROCESS_READONLY'

/** Kurz, für Plakette und Tooltip. */
export const SYSTEM_PROCESS_HINT =
  'Gehört zum Produkt: wird beim Start automatisch angelegt und aktuell gehalten. '
  + 'Bearbeiten, Veröffentlichen und Löschen sind deshalb nicht möglich. '
  + 'Für eine eigene Variante: kopieren – die Kopie ist frei änderbar.'

/** Lang, für Meldungen nach einem abgewiesenen Zugriff. */
export const SYSTEM_PROCESS_BLOCKED =
  'Das ist ein System-Prozess und kann nicht geändert werden – er gehört zum '
  + 'Produkt und wird automatisch aktuell gehalten. Wer eine eigene Variante '
  + 'braucht, kopiert ihn: die Kopie ist frei änderbar.'

/** Trägt diese Version das System-Merkmal? Maßgeblich ist allein der Server. */
export function isSystemProcess(p: { is_system?: boolean | null } | null | undefined): boolean {
  return p?.is_system === true
}

/** Hat der Server den Zugriff wegen eines System-Prozesses abgewiesen? */
export function isSystemReadonlyError(e: unknown): boolean {
  return errorCode(e) === SYSTEM_PROCESS_READONLY
}

/**
 * Dasselbe für den Editor: dort landen Server-Fehler als Issue-Liste (der
 * Envelope-Code steht am Issue), nicht als Ausnahme beim Aufrufer.
 */
export function hasSystemReadonlyIssue(issues: readonly ProcessIssue[]): boolean {
  return issues.some((i) => i.code === SYSTEM_PROCESS_READONLY)
}
