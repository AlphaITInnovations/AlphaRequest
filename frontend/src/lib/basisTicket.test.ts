/**
 * Das Basis-Ticket hat einen eigenen Knopf in der Sidebar – und darf deshalb im
 * Katalog nicht ein zweites Mal als Kachel stehen.
 *
 * Der Schlüssel ist hart verdrahtet (der Katalog-Endpunkt trägt kein Merkmal
 * dafür); dieser Test hält ihn und den Pfad an EINER Stelle fest, damit ein
 * Tippfehler nicht still die Kachel wieder einblendet.
 */
import { describe, expect, it } from 'vitest'
import {
  BASIS_TICKET_KEY, BASIS_TICKET_PATH, isBasisTicket, withoutBasisTicket,
} from '@/lib/basisTicket'

describe('Basis-Ticket', () => {
  it('kennt den Schlüssel aus dem Seed', () => {
    // backend/seeds/processes/prozess-basis-ticket.json → "key": "basis-ticket"
    expect(BASIS_TICKET_KEY).toBe('basis-ticket')
    expect(BASIS_TICKET_PATH).toBe('/prozess-auftraege/neu/basis-ticket')
  })

  it('erkennt nur den exakten Schlüssel', () => {
    expect(isBasisTicket('basis-ticket')).toBe(true)
    expect(isBasisTicket('basis-ticket-2')).toBe(false)
    expect(isBasisTicket('Basis-Ticket')).toBe(false)
    expect(isBasisTicket(null)).toBe(false)
  })

  it('nimmt genau eine Kachel aus dem Katalog', () => {
    const katalog = [{ key: 'hardware' }, { key: 'basis-ticket' }, { key: 'hotelbuchung' }]
    expect(withoutBasisTicket(katalog).map((p) => p.key)).toEqual(['hardware', 'hotelbuchung'])
  })

  it('lässt einen Katalog ohne Basis-Ticket unverändert', () => {
    const katalog = [{ key: 'hardware' }]
    expect(withoutBasisTicket(katalog)).toEqual(katalog)
  })
})
