/**
 * Das Basis-Ticket: der eine Prozess mit EIGENEM Einstieg in der Navigation.
 *
 * Die Sidebar unterscheidet wieder „Neues Prozess-Ticket" (Katalog aller
 * Prozesse) und „Neues Ticket" (das Basis-Ticket, für alles, was in keinen
 * Prozess passt). Damit derselbe Prozess nicht doppelt angeboten wird, blendet
 * der Katalog seine Kachel aus.
 *
 * WARUM STEHT DER SCHLÜSSEL HART IM CODE?
 * `GET /processes` liefert kein Merkmal, an dem sich „das ist der Basis-Prozess"
 * erkennen ließe – nur `key`, `name`, `icon`, `description` und `may_create`
 * (backend/api/v1/processes.py). Ein Merkmal dafür wäre eine Backend-Änderung.
 * Deshalb genau EINE Stelle mit dem Schlüssel, statt ihn über Sidebar, Katalog
 * und Router zu verstreuen.
 * Quelle: backend/seeds/processes/prozess-basis-ticket.json → "key": "basis-ticket".
 *
 * Ist der Prozess nicht veröffentlicht, greift der Katalog-Filter ins Leere
 * (kein Schaden) und der Knopf landet auf der ehrlichen Meldung des Formulars
 * („Dieser Prozess ist nicht (mehr) verfügbar").
 */
export const BASIS_TICKET_KEY = 'basis-ticket'

/** Direkter Weg zum Basis-Ticket-Formular (ohne Umweg über den Katalog). */
export const BASIS_TICKET_PATH = `/prozess-auftraege/neu/${BASIS_TICKET_KEY}`

export function isBasisTicket(key: string | null | undefined): boolean {
  return (key ?? '') === BASIS_TICKET_KEY
}

/** Katalog ohne das Basis-Ticket – es hat seinen eigenen Knopf. */
export function withoutBasisTicket<T extends { key: string }>(list: readonly T[]): T[] {
  return list.filter((p) => !isBasisTicket(p.key))
}
