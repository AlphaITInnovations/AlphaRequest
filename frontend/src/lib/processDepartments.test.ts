/**
 * Fachabteilungs-Stand.
 *
 * Zwei Dinge müssen stimmen, sonst wird ein Auftrag entweder unabschließbar oder
 * fälschlich als fertig gemeldet: „skipped" gilt als erledigt, und eine fehlende
 * `required`-Angabe bedeutet PFLICHT (Default der Definition).
 */
import { describe, expect, it } from 'vitest'
import type { ProcessTicketOut } from '@/types/process'
import {
  awaitsAnyDepartment, awaitsDepartment, blockingDepartments, departmentProgress,
  departmentStatusLabel, departmentTone, isDepartmentPending, isDepartmentSettled,
  isRequired, isTicketTerminal, requiredLabel, ticketsAwaitingAnyDepartment,
  ticketsAwaitingDepartment, type DepartmentAwareTicket, type DepartmentState,
} from '@/lib/processDepartments'

function dept(part: Partial<DepartmentState> & { group: string }): DepartmentState {
  return { required: true, status: 'open', by: null, by_name: null, at: null, note: null, ...part }
}

function ticket(depts: DepartmentState[] | null,
                part: Partial<DepartmentAwareTicket> = {}): DepartmentAwareTicket {
  return {
    status: 'in_progress',
    runtime: { rejected: false },
    responsibility: depts ? { kind: 'departments', departments: depts } : null,
    ...part,
  }
}

// ── Beschriftungen ────────────────────────────────────────────────────────────

describe('departmentStatusLabel', () => {
  it('beschriftet alle bekannten Stände deutsch', () => {
    expect(departmentStatusLabel('open')).toBe('Offen')
    expect(departmentStatusLabel('done')).toBe('Erledigt')
    expect(departmentStatusLabel('skipped')).toBe('Nicht zuständig')
    expect(departmentStatusLabel('rejected')).toBe('Abgelehnt')
  })

  it('zeigt einen unbekannten Status roh statt ihn zu erfinden', () => {
    expect(departmentStatusLabel('irgendwas_neues')).toBe('irgendwas_neues')
  })

  it('wertet einen fehlenden Status als offen (wie das Backend)', () => {
    expect(departmentStatusLabel(null)).toBe('Offen')
    expect(departmentStatusLabel(undefined)).toBe('Offen')
    expect(departmentStatusLabel('')).toBe('Offen')
  })
})

describe('departmentTone', () => {
  it('bildet die bekannten Stände auf sich selbst ab', () => {
    expect(departmentTone('done')).toBe('done')
    expect(departmentTone('skipped')).toBe('skipped')
    expect(departmentTone('rejected')).toBe('rejected')
    expect(departmentTone(null)).toBe('open')
  })

  it('färbt Unbekanntes neutral statt grün', () => {
    expect(departmentTone('teilweise')).toBe('unknown')
  })
})

describe('requiredLabel / isRequired', () => {
  it('behandelt eine fehlende Angabe als Pflicht', () => {
    expect(isRequired({ group: 'g_it' })).toBe(true)
    expect(requiredLabel(undefined)).toBe('Pflicht')
  })

  it('erkennt optionale Abteilungen', () => {
    expect(isRequired(dept({ group: 'g_it', required: false }))).toBe(false)
    expect(requiredLabel(false)).toBe('Optional')
  })
})

// ── Einzelner Eintrag ─────────────────────────────────────────────────────────

describe('isDepartmentSettled', () => {
  it('zählt „übersprungen" als erledigt', () => {
    expect(isDepartmentSettled('done')).toBe(true)
    expect(isDepartmentSettled('skipped')).toBe(true)
  })

  it('zählt offen, abgelehnt und Unbekanntes nicht als erledigt', () => {
    expect(isDepartmentSettled('open')).toBe(false)
    expect(isDepartmentSettled('rejected')).toBe(false)
    expect(isDepartmentSettled('teilweise')).toBe(false)
    expect(isDepartmentSettled(null)).toBe(false)
  })
})

describe('isDepartmentPending', () => {
  it('sieht nach einer Ablehnung niemanden mehr warten', () => {
    expect(isDepartmentPending(dept({ group: 'g_it', status: 'rejected' }))).toBe(false)
  })

  it('wartet bei offenem und bei unbekanntem Status', () => {
    expect(isDepartmentPending(dept({ group: 'g_it', status: 'open' }))).toBe(true)
    expect(isDepartmentPending(dept({ group: 'g_it', status: 'teilweise' }))).toBe(true)
    expect(isDepartmentPending({ group: 'g_it' })).toBe(true)
  })
})

// ── Fortschritt ───────────────────────────────────────────────────────────────

describe('departmentProgress', () => {
  it('zählt „2 von 3 erledigt" und nennt die blockierenden Pflicht-Abteilungen', () => {
    const p = departmentProgress([
      dept({ group: 'g_it', status: 'done' }),
      dept({ group: 'g_hr', status: 'skipped' }),
      dept({ group: 'g_fuhrpark', status: 'open' }),
    ])
    expect(p.text).toBe('2 von 3 erledigt')
    expect(p.total).toBe(3)
    expect(p.settled).toBe(2)
    expect(p.open).toBe(1)
    expect(p.openRequired).toBe(1)
    expect(p.ready).toBe(false)
  })

  it('lässt optionale Abteilungen den Abschluss NICHT blockieren', () => {
    const p = departmentProgress([
      dept({ group: 'g_it', status: 'done' }),
      dept({ group: 'g_marketing', status: 'open', required: false }),
    ])
    expect(p.openRequired).toBe(0)
    expect(p.ready).toBe(true)
    // Offen ist sie trotzdem – der Fortschritt darf das nicht verschweigen.
    expect(p.open).toBe(1)
    expect(p.text).toBe('1 von 2 erledigt')
  })

  it('ist bei allen erledigten Abteilungen fertig', () => {
    const p = departmentProgress([
      dept({ group: 'g_it', status: 'done' }),
      dept({ group: 'g_hr', status: 'skipped' }),
    ])
    expect(p.ready).toBe(true)
    expect(p.text).toBe('2 von 2 erledigt')
  })

  it('meldet eine Ablehnung getrennt und nicht als erledigt', () => {
    const p = departmentProgress([
      dept({ group: 'g_it', status: 'rejected' }),
      dept({ group: 'g_hr', status: 'done' }),
    ])
    expect(p.rejected).toBe(1)
    expect(p.settled).toBe(1)
    expect(p.open).toBe(0)
    // Spiegelt open_required_departments: 'rejected' ist dort nicht erledigt.
    expect(p.openRequired).toBe(1)
  })

  it('kommt mit leerer Liste und fehlender Liste klar (Phase ohne Fachabteilungen)', () => {
    for (const p of [departmentProgress([]), departmentProgress(null), departmentProgress(undefined)]) {
      expect(p.total).toBe(0)
      expect(p.ready).toBe(true)
      expect(p.text).toBe('Keine Fachabteilungen beteiligt')
    }
  })

  it('behandelt eine fehlende required-Angabe als Pflicht', () => {
    const p = departmentProgress([{ group: 'g_it', status: 'open' }])
    expect(p.required).toBe(1)
    expect(p.openRequired).toBe(1)
    expect(p.ready).toBe(false)
  })
})

describe('blockingDepartments', () => {
  it('liefert genau die offenen Pflicht-Abteilungen', () => {
    const offen = blockingDepartments([
      dept({ group: 'g_it', status: 'done' }),
      dept({ group: 'g_hr', status: 'open' }),
      dept({ group: 'g_marketing', status: 'open', required: false }),
    ])
    expect(offen.map((d) => d.group)).toEqual(['g_hr'])
  })
})

// ── Arbeitsliste ──────────────────────────────────────────────────────────────

describe('isTicketTerminal', () => {
  it('erkennt abgelehnt/archiviert am Status und am Runtime-Flag', () => {
    expect(isTicketTerminal(ticket([], { status: 'archived' }))).toBe(true)
    expect(isTicketTerminal(ticket([], { status: 'rejected' }))).toBe(true)
    expect(isTicketTerminal(ticket([], { runtime: { rejected: true } }))).toBe(true)
    expect(isTicketTerminal(ticket([]))).toBe(false)
  })
})

describe('awaitsDepartment', () => {
  const offen = ticket([
    dept({ group: 'g_it', status: 'open' }),
    dept({ group: 'g_hr', status: 'done' }),
    dept({ group: 'g_marketing', status: 'open', required: false }),
  ])

  it('wartet auf eine offene Pflicht-Abteilung', () => {
    expect(awaitsDepartment(offen, 'g_it')).toBe(true)
  })

  it('wartet standardmäßig auch auf eine offene OPTIONALE Abteilung', () => {
    expect(awaitsDepartment(offen, 'g_marketing')).toBe(true)
  })

  it('lässt sich auf die blockierenden Abteilungen einschränken', () => {
    expect(awaitsDepartment(offen, 'g_marketing', { requiredOnly: true })).toBe(false)
    expect(awaitsDepartment(offen, 'g_it', { requiredOnly: true })).toBe(true)
  })

  it('wartet nicht auf bereits quittierte Abteilungen', () => {
    expect(awaitsDepartment(offen, 'g_hr')).toBe(false)
    expect(awaitsDepartment(ticket([dept({ group: 'g_it', status: 'skipped' })]), 'g_it')).toBe(false)
    expect(awaitsDepartment(ticket([dept({ group: 'g_it', status: 'rejected' })]), 'g_it')).toBe(false)
  })

  it('wartet nicht bei abgeschlossenem oder abgelehntem Auftrag', () => {
    const depts = [dept({ group: 'g_it', status: 'open' })]
    expect(awaitsDepartment(ticket(depts, { status: 'archived' }), 'g_it')).toBe(false)
    expect(awaitsDepartment(ticket(depts, { status: 'rejected' }), 'g_it')).toBe(false)
    expect(awaitsDepartment(ticket(depts, { runtime: { rejected: true } }), 'g_it')).toBe(false)
  })

  it('wartet nicht bei einer Phase ohne Fachabteilungen', () => {
    expect(awaitsDepartment(ticket(null), 'g_it')).toBe(false)
    expect(awaitsDepartment(ticket([]), 'g_it')).toBe(false)
    expect(awaitsDepartment({ status: 'in_progress', responsibility: { kind: 'group' } }, 'g_it'))
      .toBe(false)
    expect(awaitsDepartment({ status: 'in_progress' }, 'g_it')).toBe(false)
  })

  it('bleibt bei fremder Gruppe, leerer Gruppe und fehlendem Auftrag falsch', () => {
    expect(awaitsDepartment(offen, 'g_fremd')).toBe(false)
    expect(awaitsDepartment(offen, '')).toBe(false)
    expect(awaitsDepartment(null, 'g_it')).toBe(false)
    expect(awaitsDepartment(undefined, 'g_it')).toBe(false)
  })

  // ── Einfache Gruppen-Zuständigkeit (kind='group', z. B. Basis-Ticket) ────────
  // So liefert der Server auch group_from_field aus. Ohne diese Fälle fehlte ein
  // Basis-Ticket, das bei der eigenen Abteilung liegt, im Reiter „Meine
  // Abteilungen" vollständig.

  const beiIT: DepartmentAwareTicket = {
    status: 'in_progress',
    runtime: { rejected: false },
    responsibility: { kind: 'group', group: 'g_it' },
  }

  it('zählt einen Auftrag, der bei genau dieser Abteilung liegt', () => {
    expect(awaitsDepartment(beiIT, 'g_it')).toBe(true)
    expect(awaitsDepartment(beiIT, 'g_hr')).toBe(false)
  })

  it('requiredOnly ändert daran nichts – eine Gruppen-Zuständigkeit blockiert immer', () => {
    expect(awaitsDepartment(beiIT, 'g_it', { requiredOnly: true })).toBe(true)
  })

  it('leeres Gruppen-Feld (niemand zuständig) wartet auf niemanden', () => {
    expect(awaitsDepartment({ ...beiIT, responsibility: { kind: 'group', group: null } },
      'g_it')).toBe(false)
  })

  it('terminale Gruppen-Aufträge warten nie', () => {
    expect(awaitsDepartment({ ...beiIT, status: 'archived' }, 'g_it')).toBe(false)
  })

  it('nimmt Gruppen-Aufträge in die Abteilungs-Arbeitsliste auf', () => {
    const beiHR: DepartmentAwareTicket = {
      status: 'in_progress',
      responsibility: { kind: 'group', group: 'g_hr' },
    }
    expect(ticketsAwaitingAnyDepartment([beiIT, beiHR], ['g_it'])).toEqual([beiIT])
  })

  it('akzeptiert eine echte Server-Antwort (ProcessTicketOut) unverändert', () => {
    // Strukturprüfung: die Arbeitsliste soll ohne Umbau mit der API-Form arbeiten.
    const t = {
      id: 7, process_key: 'onboarding', process_version: 3, title: 'Neu',
      status: 'in_progress', priority: 'normal', owner_id: null, owner_name: null,
      values: {},
      runtime: { current_index: 1, epoch: 0, rejected: false, sla_paused_ms: 0, phases: [] },
      current_phase: 'fach', current_phase_label: 'Fachabteilungen',
      responsibility: {
        kind: 'departments' as const,
        departments: [{ group: 'g_it', required: true, status: 'open' }],
      },
      next_timer_due_at: null, created_at: null, updated_at: null,
    } satisfies ProcessTicketOut
    expect(awaitsDepartment(t, 'g_it')).toBe(true)
  })
})

describe('ticketsAwaitingDepartment', () => {
  const t1 = ticket([dept({ group: 'g_it', status: 'open' })], { status: 'in_progress' })
  const t2 = ticket([dept({ group: 'g_it', status: 'done' })])
  const t3 = ticket([dept({ group: 'g_hr', status: 'open' }),
                     dept({ group: 'g_it', status: 'open', required: false })])
  const t4 = ticket([dept({ group: 'g_it', status: 'open' })], { status: 'rejected' })

  it('filtert und behält die Reihenfolge', () => {
    expect(ticketsAwaitingDepartment([t1, t2, t3, t4], 'g_it')).toEqual([t1, t3])
  })

  it('beachtet requiredOnly', () => {
    expect(ticketsAwaitingDepartment([t1, t2, t3, t4], 'g_it', { requiredOnly: true }))
      .toEqual([t1])
  })

  it('liefert bei leerer oder fehlender Liste ein leeres Ergebnis', () => {
    expect(ticketsAwaitingDepartment([], 'g_it')).toEqual([])
    expect(ticketsAwaitingDepartment(null, 'g_it')).toEqual([])
    expect(ticketsAwaitingDepartment(undefined, 'g_it')).toEqual([])
  })
})

describe('awaitsAnyDepartment / ticketsAwaitingAnyDepartment', () => {
  const t1 = ticket([dept({ group: 'g_it', status: 'open' })])
  const t2 = ticket([dept({ group: 'g_hr', status: 'open' })])
  const t3 = ticket([dept({ group: 'g_fuhrpark', status: 'open' })])

  it('trifft bei Mehrfach-Mitgliedschaft und zählt jeden Auftrag nur einmal', () => {
    expect(awaitsAnyDepartment(t1, ['g_hr', 'g_it'])).toBe(true)
    const treffer = ticketsAwaitingAnyDepartment([t1, t2, t3], ['g_it', 'g_hr'])
    expect(treffer).toEqual([t1, t2])
  })

  it('bleibt ohne Gruppen leer', () => {
    expect(awaitsAnyDepartment(t1, [])).toBe(false)
    expect(awaitsAnyDepartment(t1, null)).toBe(false)
    expect(ticketsAwaitingAnyDepartment([t1, t2], [])).toEqual([])
  })
})
