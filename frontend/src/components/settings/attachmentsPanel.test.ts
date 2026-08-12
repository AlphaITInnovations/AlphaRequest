/**
 * Verlinkung der Admin-Anhang-Übersicht.
 *
 * Kein Mounting (das Projekt hat kein @vue/test-utils/jsdom) – geprüft werden die
 * reinen Helfer, die entscheiden, WOHIN eine Zeile führt. Genau hier lag der Bug:
 * Prozess-Anhänge zeigten auf /admin/tickets/:id und damit auf ein fremdes
 * Alt-Ticket mit derselben ID.
 */
import { describe, it, expect } from 'vitest'
import {
  entityPath, entityLabel, ENTITY_TICKET, ENTITY_PROCESS_TICKET,
} from './AttachmentsPanel.vue'

describe('entityPath', () => {
  it('verlinkt Alt-Tickets auf die Admin-Detailansicht', () => {
    expect(entityPath(ENTITY_TICKET, 7)).toBe('/admin/tickets/7')
  })

  it('verlinkt Prozess-Anhänge auf den Prozess-Auftrag – NICHT auf das Alt-Ticket', () => {
    expect(entityPath(ENTITY_PROCESS_TICKET, 7)).toBe('/prozess-auftraege/7')
    // Gleiche ID, zwei verschiedene Ziele – der Kern des Problems.
    expect(entityPath(ENTITY_PROCESS_TICKET, 7)).not.toBe(entityPath(ENTITY_TICKET, 7))
  })

  it('behandelt unbekannten/fehlenden entity_type wie das Alt-System (Spalten-Default)', () => {
    expect(entityPath(null, 7)).toBe('/admin/tickets/7')
    expect(entityPath(undefined, 7)).toBe('/admin/tickets/7')
  })

  it('ohne ID kein Ziel (Anhang ohne Entität)', () => {
    expect(entityPath(ENTITY_TICKET, null)).toBeNull()
    expect(entityPath(ENTITY_PROCESS_TICKET, undefined)).toBeNull()
    expect(entityPath(ENTITY_TICKET, 0)).toBeNull()
  })
})

describe('entityLabel', () => {
  it('kennzeichnet beide Welten unterscheidbar', () => {
    expect(entityLabel(ENTITY_PROCESS_TICKET)).toBe('Prozess')
    expect(entityLabel(ENTITY_TICKET)).toBe('Ticket')
    expect(entityLabel(null)).toBe('Ticket')
  })
})

describe('Werte der Welt-Konstanten', () => {
  it('entsprechen dem Backend (att_db.ENTITY_* / Query-Filter)', () => {
    expect(ENTITY_TICKET).toBe('ticket')
    expect(ENTITY_PROCESS_TICKET).toBe('process_ticket')
  })
})
