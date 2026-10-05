import { describe, it, expect } from 'vitest'
import { normalizeField } from './processNormalize'
import { applyPrefill, matchOption } from './processPrefill'

/** Client-Spiegel von services/process_prefill – nur die Anzeige beim Anlegen
 *  (autoritativ setzt der Server; der Anlege-Dialog nutzt bevorzugt den Endpunkt
 *  /processes/{key}/create-prefill, dieser Spiegel ist die Rückfallebene). */
describe('applyPrefill (Client-Spiegel)', () => {
  const anrede = normalizeField({
    key: 'b.anrede', widget: 'select',
    options: [{ value: 'Herr' }, { value: 'Frau' }, { value: 'Divers' }],
    prefill: { source: 'employee', field: 'salutation' },
  })

  it('füllt Text-/Relationsfelder aus employee und user', () => {
    const nachname = normalizeField({
      key: 'b.nachname', widget: 'text', prefill: { source: 'employee', field: 'last_name' } })
    const mail = normalizeField({
      key: 'b.mail', widget: 'text', prefill: { source: 'user', field: 'email' } })
    const nl = normalizeField({
      key: 'b.nl', widget: 'text', prefill: { source: 'employee', field: 'location.name' } })
    const out = applyPrefill([nachname, mail, nl], {
      email: 'a@b.de', employee: { last_name: 'Popp', location: { name: 'Nürnberg' } },
    }, {})
    expect(out['b.nachname']).toBe('Popp')
    expect(out['b.mail']).toBe('a@b.de')
    expect(out['b.nl']).toBe('Nürnberg')
  })

  it('bildet einen select-Prefill unabhängig von Groß-/Kleinschreibung auf die Option ab', () => {
    expect(applyPrefill([anrede], { employee: { salutation: 'herr' } }, {})['b.anrede']).toBe('Herr')
    expect(applyPrefill([anrede], { employee: { salutation: 'FRAU' } }, {})['b.anrede']).toBe('Frau')
  })

  it('trifft eine Option auch über deren Label', () => {
    const f = normalizeField({
      key: 'b.anrede', widget: 'select',
      options: [{ value: 'm', label: 'Herr' }, { value: 'w', label: 'Frau' }],
      prefill: { source: 'employee', field: 'salutation' },
    })
    expect(applyPrefill([f], { employee: { salutation: 'Herr' } }, {})['b.anrede']).toBe('m')
  })

  it('lässt ein select ohne passende Option leer (statt ungültigen Wert)', () => {
    expect('b.anrede' in applyPrefill([anrede], { employee: { salutation: 'weiß nicht' } }, {}))
      .toBe(false)
  })

  it('macht aus einer Directus-Zahl in einem Text-Feld einen String', () => {
    const idFeld = normalizeField({
      key: 'b.id', widget: 'text', prefill: { source: 'employee', field: 'id' } })
    const plz = normalizeField({
      key: 'b.plz', widget: 'text', prefill: { source: 'employee', field: 'zip' } })
    const out = applyPrefill([idFeld, plz], { employee: { id: 42, zip: 90402 } }, {})
    expect(out['b.id']).toBe('42')
    expect(out['b.plz']).toBe('90402')
  })

  it('nimmt für ein directus-Feld die Roh-ID als String (Zahl oder Objekt)', () => {
    const f = normalizeField({
      key: 'b.nl', widget: 'directus', directusSource: 'niederlassung',
      prefill: { source: 'employee', field: 'location' } })
    expect(applyPrefill([f], { employee: { location: 8080 } }, {})['b.nl']).toBe('8080')
    expect(applyPrefill([f], { employee: { location: { id: 42, name: 'Berlin' } } }, {})['b.nl'])
      .toBe('42')
  })
})

/** matchOption ist exportiert, weil auch das Live-Auto-Fill der directus-Auswahl
 *  (SchemaForm coerceForTarget) ein select-Ziel case-insensitiv vorwählen muss. */
describe('matchOption (geteilt mit dem directus-Live-Fill)', () => {
  const anrede = normalizeField({
    key: 'b.anrede', widget: 'select',
    options: [{ value: 'Herr' }, { value: 'Frau' }, { value: 'Divers' }] })

  it('bildet case-insensitiv auf den Options-Wert ab', () => {
    expect(matchOption('herr', anrede)).toBe('Herr')
    expect(matchOption('FRAU', anrede)).toBe('Frau')
  })

  it('bildet ein Label auf den Options-Wert ab', () => {
    const f = normalizeField({
      key: 'b.anrede', widget: 'select', options: [{ value: 'm', label: 'Herr' }] })
    expect(matchOption('herr', f)).toBe('m')
  })

  it('gibt undefined ohne Treffer (und ohne allowOther)', () => {
    expect(matchOption('unbekannt', anrede)).toBeUndefined()
  })
})
