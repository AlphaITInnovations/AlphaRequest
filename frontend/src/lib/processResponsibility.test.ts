/**
 * Anzeige der Zuständigkeit („nächster Bearbeiter").
 *
 * Zwei Dinge müssen stimmen, sonst bleibt im Betrieb ein Auftrag liegen:
 *  - ein LEERES Quellfeld muss als „niemand zuständig" erkennbar sein (der
 *    Server liefert dann `group: null` / `user: null`),
 *  - „weiterreichen" darf nur angeboten werden, wenn der Server das Quellfeld in
 *    dieser Phase auch zum Bearbeiten freigegeben hat – sonst verwirft der PATCH
 *    die Änderung still.
 */
import { describe, expect, it } from 'vitest'
import type { ResolvedResponsibility } from '@/types/process'
import {
  describeResponsibility, handoverTarget, type ResponsibilityIn,
} from '@/lib/processResponsibility'

const NAMEN = {
  groupName: (id: string) => ({ g1: 'IT', g2: 'Personal' }[id] ?? id),
  userName: (id: string) => ({ u1: 'Erika Muster' }[id] ?? id),
  fieldName: (key: string) => ({ zustaendig: 'Zuständige Abteilung' }[key] ?? key),
  ownerName: 'Max Antrag',
}

describe('describeResponsibility – benannte Stellen', () => {
  it('löst eine Gruppen-ID zum Namen auf', () => {
    const v = describeResponsibility({ kind: 'group', group: 'g1' }, NAMEN)
    expect(v.kind).toBe('group')
    expect(v.name).toBe('IT')
    expect(v.roleLabel).toBe('Fachabteilung')
    expect(v.missing).toBe(false)
    expect(v.missingHint).toBe('')
  })

  it('löst eine Personen-ID zum Anzeigenamen auf', () => {
    expect(describeResponsibility({ kind: 'user', user: 'u1' }, NAMEN).name).toBe('Erika Muster')
  })

  it('zeigt die ID, wenn kein Name bekannt ist – statt sie zu verschweigen', () => {
    expect(describeResponsibility({ kind: 'group', group: 'unbekannt' }, NAMEN).name)
      .toBe('unbekannt')
    expect(describeResponsibility({ kind: 'user', user: 'u9' }, {}).name).toBe('u9')
  })

  it('nennt bei owner die antragstellende Person', () => {
    const v = describeResponsibility({ kind: 'owner' }, NAMEN)
    expect(v.name).toBe('Max Antrag')
    expect(v.missing).toBe(false)
  })

  it('bleibt bei owner ohne Namen trotzdem geklärt', () => {
    const v = describeResponsibility({ kind: 'owner' }, { ownerName: '  ' })
    expect(v.name).toBe('Ersteller:in des Auftrags')
    expect(v.missing).toBe(false)
  })

  it('macht aus einem Feld-Bezug eine erkennbare Herkunft', () => {
    const v = describeResponsibility(
      { kind: 'group', group: 'g2', from_field: 'zustaendig', assignable: true }, NAMEN)
    expect(v.name).toBe('Personal')
    expect(v.roleLabel).toBe('Fachabteilung (aus dem Auftrag)')
    expect(v.fromField).toBe('zustaendig')
  })
})

describe('describeResponsibility – niemand zuständig', () => {
  it('erkennt das leere Quellfeld und nennt es beim Namen', () => {
    const v = describeResponsibility(
      { kind: 'group', group: null, from_field: 'zustaendig', assignable: true }, NAMEN)
    expect(v.missing).toBe(true)
    expect(v.name).toBe('')
    expect(v.missingHint).toContain('Zuständige Abteilung')
  })

  it('gilt genauso für ein leeres Personen-Feld', () => {
    const v = describeResponsibility(
      { kind: 'user', user: null, from_field: 'bearbeiter', assignable: true }, NAMEN)
    expect(v.missing).toBe(true)
    // Ohne Beschriftung wird der Schlüssel gezeigt – nie ein erfundener Name.
    expect(v.missingHint).toContain('bearbeiter')
  })

  it('meldet eine Gruppen-Zuständigkeit ohne Gruppe auch ohne Quellfeld', () => {
    const v = describeResponsibility({ kind: 'group', group: '  ' }, NAMEN)
    expect(v.missing).toBe(true)
    expect(v.missingHint).toContain('niemand zuständig')
  })

  it('meldet eine Fachabteilungs-Phase, zu der keine Abteilung passt', () => {
    const v = describeResponsibility({ kind: 'departments', departments: [] }, NAMEN)
    expect(v.missing).toBe(true)
    expect(v.missingHint).toContain('keine Fachabteilung')
  })

  it('behandelt fehlende und unbekannte Zuständigkeit als offenes Problem', () => {
    expect(describeResponsibility(null).missing).toBe(true)
    expect(describeResponsibility(undefined).missing).toBe(true)
    expect(describeResponsibility({ kind: 'unknown' }).missing).toBe(true)
    const exotisch = describeResponsibility({ kind: 'irgendwas' })
    expect(exotisch.missing).toBe(true)
    // Rohwert nennen, damit die Ursache auffindbar ist.
    expect(exotisch.roleLabel).toContain('irgendwas')
  })
})

describe('describeResponsibility – Fachabteilungen', () => {
  it('zählt nur, statt die Namen zu wiederholen (die stehen in der Karte)', () => {
    const v = describeResponsibility({
      kind: 'departments',
      departments: [{ group: 'g1', status: 'done' }, { group: 'g2', status: 'open' }],
    }, NAMEN)
    expect(v.name).toBe('2 Fachabteilungen')
    expect(v.missing).toBe(false)
  })

  it('bleibt im Singular korrekt', () => {
    const v = describeResponsibility({
      kind: 'departments', departments: [{ group: 'g1', status: 'open' }],
    }, NAMEN)
    expect(v.name).toBe('1 Fachabteilung')
  })
})

describe('describeResponsibility – Server-Typ passt hinein', () => {
  it('nimmt `ResolvedResponsibility` unverändert an', () => {
    const vomServer: ResolvedResponsibility = {
      kind: 'group', group: 'g1', from_field: 'zustaendig', assignable: true,
    }
    const rein: ResponsibilityIn = vomServer
    expect(describeResponsibility(rein, NAMEN).name).toBe('IT')
  })
})

describe('handoverTarget', () => {
  const ausFeld: ResponsibilityIn = {
    kind: 'group', group: 'g1', from_field: 'zustaendig', assignable: true,
  }

  it('bietet das Umstellen an, wenn das Quellfeld editierbar ist', () => {
    expect(handoverTarget(ausFeld, ['titel', 'zustaendig'], true))
      .toEqual({ field: 'zustaendig', pick: 'group', current: 'g1' })
  })

  it('bietet bei leerem Feld an, jemanden EINZUTRAGEN', () => {
    expect(handoverTarget({ ...ausFeld, group: null }, ['zustaendig'], true))
      .toEqual({ field: 'zustaendig', pick: 'group', current: '' })
  })

  it('unterscheidet Personen- und Gruppen-Auswahl', () => {
    expect(handoverTarget(
      { kind: 'user', user: 'u1', from_field: 'bearbeiter' }, ['bearbeiter'], true)?.pick)
      .toBe('user')
  })

  it('schweigt, wenn das Feld in dieser Phase nicht editierbar ist', () => {
    expect(handoverTarget(ausFeld, ['titel'], true)).toBeNull()
    expect(handoverTarget(ausFeld, [], true)).toBeNull()
    expect(handoverTarget(ausFeld, undefined, true)).toBeNull()
  })

  it('schweigt ohne Bearbeitungsrecht – `editable_fields` ist kein Rollen-Gate', () => {
    // Beobachter:innen und die Ersteller:in bekommen die Liste gefüllt, dürfen
    // aber nicht patchen: ein Knopf hier endete mit 403.
    expect(handoverTarget(ausFeld, ['zustaendig'], false)).toBeNull()
  })

  it('schweigt ohne Quellfeld – eine feste Gruppe gehört in die Definition', () => {
    expect(handoverTarget({ kind: 'group', group: 'g1' }, ['zustaendig'], true)).toBeNull()
    expect(handoverTarget({ kind: 'owner' }, ['zustaendig'], true)).toBeNull()
    expect(handoverTarget(null, ['zustaendig'], true)).toBeNull()
  })

  it('schweigt bei Fachabteilungen – dort wird quittiert, nicht weitergereicht', () => {
    expect(handoverTarget(
      { kind: 'departments', departments: [{ group: 'g1' }], from_field: 'x' }, ['x'], true))
      .toBeNull()
  })
})
