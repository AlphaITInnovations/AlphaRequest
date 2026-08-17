import { describe, expect, it } from 'vitest'
import { mailFieldRefs, mailVariables } from './mailTemplate'

describe('mailVariables', () => {
  it('findet Variablen ohne Dopplung, in Reihenfolge, trimmt Leerzeichen', () => {
    const tpl = 'Hallo {{title}} / {{base.first_name}} {{ base.last_name }} #{{id}} {{base.first_name}}'
    expect(mailVariables(tpl)).toEqual(['title', 'base.first_name', 'base.last_name', 'id'])
  })

  it('ist robust gegen leere Eingaben', () => {
    expect(mailVariables(null)).toEqual([])
    expect(mailVariables('')).toEqual([])
    expect(mailVariables('kein Platzhalter hier')).toEqual([])
  })
})

describe('mailFieldRefs', () => {
  it('lässt die Spezial-Variablen title/id weg', () => {
    expect(mailFieldRefs('{{title}} {{id}} {{base.name}}')).toEqual(['base.name'])
  })
})
