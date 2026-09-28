/**
 * Verlinkung der Admin-Anhang-Übersicht.
 *
 * Kein Mounting (das Projekt hat kein @vue/test-utils/jsdom) – geprüft werden die
 * reinen Helfer, die entscheiden, WOHIN eine Zeile führt. Genau hier lag der Bug:
 * Prozess-Anhänge zeigten auf die Admin-Detailansicht des Alt-Systems und damit
 * auf ein fremdes Ticket mit derselben ID. Seit das Alt-System entfernt ist, ist
 * die Gegenprobe wichtiger geworden: eine Alt-Zeile darf NICHT ersatzweise auf
 * /prozess-auftraege/:id zeigen.
 */
import { describe, it, expect } from 'vitest'
import {
  entityPath, entityLabel, ENTITY_TICKET, ENTITY_PROCESS_TICKET,
} from './AttachmentsPanel.vue'

describe('entityPath', () => {
  it('verlinkt Prozess-Anhänge auf den Prozess-Auftrag', () => {
    expect(entityPath(ENTITY_PROCESS_TICKET, 7)).toBe('/prozess-auftraege/7')
  })

  it('verlinkt Alt-Anhänge NICHT – die Zielseite gibt es nicht mehr', () => {
    // Gleiche ID, zwei Welten: /prozess-auftraege/7 wäre ein fremder Auftrag.
    expect(entityPath(ENTITY_TICKET, 7)).toBeNull()
  })

  it('rät bei unbekanntem/fehlendem entity_type kein Ziel', () => {
    expect(entityPath(null, 7)).toBeNull()
    expect(entityPath(undefined, 7)).toBeNull()
    expect(entityPath('etwas-neues', 7)).toBeNull()
  })

  it('ohne ID kein Ziel (Anhang ohne Entität)', () => {
    expect(entityPath(ENTITY_TICKET, null)).toBeNull()
    expect(entityPath(ENTITY_PROCESS_TICKET, undefined)).toBeNull()
    expect(entityPath(ENTITY_PROCESS_TICKET, 0)).toBeNull()
  })
})

describe('entityLabel', () => {
  it('kennzeichnet beide Welten unterscheidbar', () => {
    expect(entityLabel(ENTITY_PROCESS_TICKET)).toBe('Prozess')
    expect(entityLabel(ENTITY_TICKET)).toBe('Alt-System')
    expect(entityLabel(null)).toBe('Alt-System')
  })
})

describe('Werte der Welt-Konstanten', () => {
  it('entsprechen dem Backend (att_db.ENTITY_* / Query-Filter)', () => {
    expect(ENTITY_TICKET).toBe('ticket')
    expect(ENTITY_PROCESS_TICKET).toBe('process_ticket')
  })
})
