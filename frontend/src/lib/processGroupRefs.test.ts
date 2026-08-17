import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { normalizeDefinition } from './processNormalize'
import {
  collectGroupRefs, isGroupPlaceholder, replaceGroupRefs, unknownGroupRefs,
} from './processGroupRefs'

const PH_IT = 'HIER_GRUPPEN_ID_IT_EINSETZEN'
const PH_HR = 'HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN'
const PH_SGL = 'HIER_GRUPPEN_ID_SEKRETARIAT_GL_EINSETZEN'

const GRUPPEN = [
  { id: 'gid-it', name: 'IT' },
  { id: 'gid-hr', name: 'personalabteilung' },   // Groß/klein darf abweichen
  { id: 'gid-fp', name: 'Fuhrpark' },
]

/** Definition mit Gruppen-Referenzen an allen Stellen, die es gibt. */
function defn() {
  return normalizeDefinition({
    key: 'test', name: 'Test',
    createPermissions: { everyone: false, groups: [PH_SGL], users: [] },
    fields: [
      { key: 'a.eins', label: 'Eins', widget: 'text',
        visibility: { confidential: true, visibleToGroups: [PH_HR, 'gid-fp'] },
        // Prosa, die einen Platzhalter ERWÄHNT – darf nie ersetzt werden.
        help: `Sichtbar nur für ${PH_HR}.` },
      { key: 'a.zwei', label: 'Zwei', widget: 'text' },
      // Options-Werte sind KEINE Gruppen-Stellen – auch wenn dort zufällig ein
      // Platzhalter oder eine fremde ID als kompletter Wert steht.
      { key: 'a.drei', label: 'Drei', widget: 'select',
        options: [{ value: PH_IT, label: null }, { value: 'fremd-99', label: null }] },
    ],
    automations: [
      { id: 'top_mail', trigger: { type: 'on_enter' },
        action: { type: 'notify', to: `group:${PH_IT}`, template: 't' } },
      { id: 'top_owner', trigger: { type: 'on_enter' },
        action: { type: 'notify', to: 'owner', template: 't' } },
    ],
    phases: [
      { key: 'start', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'a.eins' }] },
      { key: 'arbeit', kind: 'work',
        responsibility: { kind: 'group', group: PH_SGL },
        automations: [
          { id: 'phase_mail', trigger: { type: 'on_enter' },
            action: { type: 'notify', to: 'group:fremd-99', template: 't' } },
        ],
        fields: [{ ref: 'a.zwei' }] },
      { key: 'review', kind: 'department_review',
        responsibility: { kind: 'departments',
          rule: [{ group: PH_IT }, { group: 'gid-fp' }] },
        fields: [] },
    ],
  })
}

describe('isGroupPlaceholder', () => {
  it('erkennt nur exakte Platzhalter', () => {
    expect(isGroupPlaceholder(PH_IT)).toBe(true)
    expect(isGroupPlaceholder('gid-it')).toBe(false)
    expect(isGroupPlaceholder(`Hinweis: ${PH_IT}`)).toBe(false)
  })
})

describe('collectGroupRefs', () => {
  it('findet alle Gruppen-Stellen, aber keine Prosa und keine Nicht-Gruppen-Empfänger', () => {
    const refs = collectGroupRefs(defn())
    const werte = refs.map((r) => r.value)
    expect(werte).toContain(PH_HR)         // Sichtbarkeit
    expect(werte).toContain(PH_IT)         // Automation (top) + rule
    expect(werte).toContain(PH_SGL)        // responsibility.group + createPermissions
    expect(werte).toContain('fremd-99')    // Phasen-Automation
    expect(werte).toContain('gid-fp')      // echte ID zählt auch als Stelle
    expect(werte).not.toContain('owner')   // Empfänger ohne group:-Präfix
    // Die Hilfetext-Erwähnung ist KEINE Stelle: PH_HR kommt nur 1× vor.
    expect(werte.filter((w) => w === PH_HR)).toHaveLength(1)
    // Options-Werte zählen nicht: PH_IT nur an Automation + rule.
    expect(werte.filter((w) => w === PH_IT)).toHaveLength(2)
  })
})

describe('unknownGroupRefs', () => {
  it('liefert je fremdem Wert einen Eintrag mit Klartext und Zähler', () => {
    const rows = unknownGroupRefs(defn(), GRUPPEN)
    const byValue = Object.fromEntries(rows.map((r) => [r.value, r]))

    expect(byValue['gid-fp']).toBeUndefined()          // bekannt → kein Eintrag

    expect(byValue[PH_HR]).toMatchObject({
      placeholder: true, label: 'Personalabteilung', sites: 1,
    })
    expect(byValue[PH_IT]).toMatchObject({ sites: 2 })
    expect(byValue[PH_SGL]).toMatchObject({ label: 'Sekretariat GL', sites: 2 })
    expect(byValue['fremd-99']).toMatchObject({ placeholder: false, label: 'fremd-99' })

    // Es wird nichts empfohlen/vorbelegt – die Zeilen tragen keinen Vorschlag.
    expect(rows.every((r) => !('suggestion' in r))).toBe(true)

    // Platzhalter (blockieren den Import) stehen vor echten IDs.
    const letzterPlatzhalter = rows.map((r) => r.placeholder).lastIndexOf(true)
    const ersteId = rows.map((r) => r.placeholder).indexOf(false)
    expect(letzterPlatzhalter).toBeLessThan(ersteId)
  })
})

describe('replaceGroupRefs', () => {
  it('ersetzt an allen Gruppen-Stellen, aber nie im Text – und mutiert die Eingabe nicht', () => {
    const original = defn()
    const out = replaceGroupRefs(original, {
      [PH_IT]: 'gid-it', [PH_HR]: 'gid-hr', [PH_SGL]: 'gid-sgl', 'fremd-99': 'gid-fp',
    })

    expect(out.fields[0].visibility?.visibleToGroups).toEqual(['gid-hr', 'gid-fp'])
    expect(out.automations[0].action.to).toBe('group:gid-it')
    expect(out.automations[1].action.to).toBe('owner')
    expect(out.phases[1].responsibility.group).toBe('gid-sgl')
    expect(out.phases[1].automations[0].action.to).toBe('group:gid-fp')
    expect(out.phases[2].responsibility.rule.map((r) => r.group)).toEqual(['gid-it', 'gid-fp'])
    expect(out.createPermissions.groups).toEqual(['gid-sgl'])
    // Erwähnung im Hilfetext bleibt Text.
    expect(out.fields[0].help).toContain(PH_HR)

    // Eingabe unangetastet, nicht zugeordnete Werte bleiben stehen.
    expect(original.phases[1].responsibility.group).toBe(PH_SGL)
    const teil = replaceGroupRefs(original, { [PH_IT]: 'gid-it' })
    expect(teil.phases[1].responsibility.group).toBe(PH_SGL)
  })

  it('ersetzt einen zugeordneten PLATZHALTER auch an Nicht-Gruppen-Stellen, eine echte ID aber nicht', () => {
    const out = replaceGroupRefs(defn(), { [PH_IT]: 'gid-it', 'fremd-99': 'gid-fp' })
    // Options-Werte: Platzhalter wird mitgezogen (spiegelt seeds.replace_placeholders),
    // die echte ID bleibt stehen (nur Gruppen-Stellen werden für IDs umgeschrieben).
    expect(out.fields[2].options.map((o) => o.value)).toEqual(['gid-it', 'fremd-99'])
    expect(out.phases[1].automations[0].action.to).toBe('group:gid-fp')  // Gruppen-Stelle: ja
  })

  it('klont einen Vue-Reactive-Proxy, ohne zu werfen (structuredClone-Falle)', () => {
    // Das Modal übergibt parsed.value aus einem tiefen ref() – ein Proxy, den
    // structuredClone mit DataCloneError ablehnen würde.
    const proxy = ref(defn()).value
    const out = replaceGroupRefs(proxy, { [PH_SGL]: 'gid-sgl' })
    expect(out.phases[1].responsibility.group).toBe('gid-sgl')
    expect(out.createPermissions.groups).toEqual(['gid-sgl'])
  })
})
