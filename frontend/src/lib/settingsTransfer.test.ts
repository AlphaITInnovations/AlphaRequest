import { describe, it, expect } from 'vitest'
import { extractList } from './settingsTransfer'

describe('extractList', () => {
  it('nimmt ein nacktes Array', () => {
    expect(extractList([{ name: 'A' }], 'companies', 'alpharequest:companies'))
      .toEqual([{ name: 'A' }])
  })

  it('zieht die Liste aus einem passenden Hüllobjekt', () => {
    const parsed = { kind: 'alpharequest:companies', version: 1, companies: [{ name: 'A' }, { name: 'B' }] }
    expect(extractList(parsed, 'companies', 'alpharequest:companies')).toHaveLength(2)
  })

  it('akzeptiert ein Hüllobjekt ohne kind', () => {
    expect(extractList({ groups: [{ name: 'IT' }] }, 'groups', 'alpharequest:fachabteilungen'))
      .toEqual([{ name: 'IT' }])
  })

  it('lehnt einen falschen kind ab (keine Firmen-Datei im Fachabteilungs-Import)', () => {
    const parsed = { kind: 'alpharequest:companies', companies: [] }
    expect(() => extractList(parsed, 'groups', 'alpharequest:fachabteilungen')).toThrow(/Falscher Dateityp/)
  })

  it('wirft, wenn keine Liste gefunden wird', () => {
    expect(() => extractList({ foo: 'bar' }, 'companies', 'alpharequest:companies')).toThrow(/keine gültige Liste/)
    expect(() => extractList(42, 'companies', 'alpharequest:companies')).toThrow(/keine gültige Liste/)
  })
})
