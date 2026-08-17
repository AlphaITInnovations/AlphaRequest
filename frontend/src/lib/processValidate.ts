/**
 * Client-Validierung einer ProcessDefinition – Spiegel der Server-Regeln aus
 * backend/schemas/process_definition.py (_integrity, Feld-/Phasen-/Action-Regeln).
 *
 * Zweck: Fehler VOR dem Speichern zeigen und den Speichern-Knopf sperren.
 * Autoritativ bleibt der Server; Warnungen (severity 'warning') blockieren nicht.
 */
import type {
  Condition, ProcessDefinition, ProcessIssue,
} from '@/types/process'
import {
  ACTION_TYPES, ENTER_STATUS, PHASE_KINDS, PHASE_VIEWS, PRIORITIES, RECIPIENTS,
  RESPONSIBILITY_KINDS,
  SCHEMA_VERSION, SEQUENCE_COUNTERS, WIDGETS_SUB, WIDGETS_TOP, WIDGET_LABEL, backToTarget,
  isValidFieldKey, isValidOnReject, isValidPhaseKey, isValidProcessKey,
} from '@/lib/processSchema'
import { isValidDuration } from '@/lib/isoDuration'
import { mailFieldRefs } from '@/lib/mailTemplate'

const DSL_OPS = ['==', '!=', 'in', 'truthy', 'and', 'or', 'not']

/** Alle Feld-Referenzen aus einem DSL-Ausdruck einsammeln. */
export function dslRefs(cond: Condition | null | undefined): string[] {
  if (!cond || typeof cond !== 'object') return []
  const keys = Object.keys(cond)
  if (keys.length !== 1) return []
  const op = keys[0]
  const arg = (cond as any)[op]
  if (op === '==' || op === '!=' || op === 'in') {
    return Array.isArray(arg) && typeof arg[0] === 'string' ? [arg[0]] : []
  }
  if (op === 'truthy') return typeof arg === 'string' ? [arg] : []
  if (op === 'and' || op === 'or') {
    return Array.isArray(arg) ? arg.flatMap((c) => dslRefs(c)) : []
  }
  if (op === 'not') return dslRefs(arg)
  return []
}

/** Wohlgeformtheit eines DSL-Ausdrucks (wie validate_condition serverseitig). */
export function isWellFormedCondition(cond: any): boolean {
  if (!cond || typeof cond !== 'object' || Array.isArray(cond)) return false
  const keys = Object.keys(cond)
  if (keys.length !== 1) return false
  const op = keys[0]
  const arg = cond[op]
  if (!DSL_OPS.includes(op)) return false
  if (op === 'in') {
    return Array.isArray(arg) && arg.length === 2 && typeof arg[0] === 'string' && Array.isArray(arg[1])
  }
  if (op === '==' || op === '!=') {
    return Array.isArray(arg) && arg.length === 2 && typeof arg[0] === 'string'
  }
  if (op === 'truthy') return typeof arg === 'string'
  if (op === 'and' || op === 'or') {
    return Array.isArray(arg) && arg.length > 0 && arg.every(isWellFormedCondition)
  }
  if (op === 'not') return isWellFormedCondition(arg)
  return false
}

function err(path: string, anchor: string, code: string, message: string): ProcessIssue {
  return { path, anchor, code, severity: 'error', message, source: 'client' }
}
function warn(path: string, anchor: string, code: string, message: string): ProcessIssue {
  return { path, anchor, code, severity: 'warning', message, source: 'client' }
}

/**
 * Prüft eine Definition. `knownGroupIds` (optional) erzeugt Warnungen für
 * Gruppen-IDs, die es nicht (mehr) gibt – der Server prüft das nicht.
 */
export function validateDefinition(
  d: ProcessDefinition, knownGroupIds?: Set<string>,
): ProcessIssue[] {
  const out: ProcessIssue[] = []
  const TOP = 'pe-top'

  // ── Kopfdaten ──
  if (!isValidProcessKey(d.key)) {
    out.push(err('key', TOP, 'INVALID_KEY',
      'Prozess-Schlüssel: nur a–z, 0–9 und „-", Beginn alphanumerisch, max. 64 Zeichen.'))
  }
  if (!d.name?.trim()) out.push(err('name', TOP, 'REQUIRED', 'Der Prozess braucht einen Namen.'))
  if (d.schemaVersion !== SCHEMA_VERSION) {
    out.push(err('schemaVersion', TOP, 'UNSUPPORTED',
      `Nicht unterstützte schemaVersion ${d.schemaVersion} (erwartet ${SCHEMA_VERSION}).`))
  }

  // ── Feld-Katalog ──
  const seenFieldKeys = new Set<string>()
  const catalog = new Set(d.fields.map((f) => f.key))
  d.fields.forEach((f, i) => {
    const anchor = `pe-catalog-${i}`
    const p = `fields.${i}`
    if (!f.key) out.push(err(`${p}.key`, anchor, 'REQUIRED', 'Feld braucht einen Schlüssel.'))
    else if (!isValidFieldKey(f.key)) {
      out.push(err(`${p}.key`, anchor, 'INVALID_KEY',
        `Feld-Schlüssel „${f.key}": erlaubt sind Buchstaben, Ziffern, „_" und Punkte.`))
    } else if (seenFieldKeys.has(f.key)) {
      out.push(err(`${p}.key`, anchor, 'DUPLICATE_KEY', `Doppelter Feld-Schlüssel „${f.key}".`))
    }
    seenFieldKeys.add(f.key)

    if (!WIDGETS_TOP.includes(f.widget)) {
      out.push(err(`${p}.widget`, anchor, 'UNSUPPORTED_WIDGET',
        `Feldtyp „${f.widget}" ist nicht verfügbar.`))
    }
    if (f.widget === 'collection' && f.item.length === 0) {
      out.push(err(`${p}.item`, anchor, 'REQUIRED',
        'Eine Wiederholgruppe braucht mindestens ein Unterfeld.'))
    }
    if (f.widget !== 'collection' && f.item.length > 0) {
      out.push(err(`${p}.item`, anchor, 'INVALID',
        'Unterfelder sind nur bei einer Wiederholgruppe erlaubt.'))
    }
    const subKeys = new Set<string>()
    f.item.forEach((sf, j) => {
      if (!sf.key) {
        out.push(err(`${p}.item.${j}.key`, anchor, 'REQUIRED', 'Unterfeld braucht einen Schlüssel.'))
      } else if (subKeys.has(sf.key)) {
        out.push(err(`${p}.item.${j}.key`, anchor, 'DUPLICATE_KEY',
          `Doppeltes Unterfeld „${sf.key}".`))
      }
      subKeys.add(sf.key)
      if (!WIDGETS_SUB.includes(sf.widget)) {
        out.push(err(`${p}.item.${j}.widget`, anchor, 'UNSUPPORTED_WIDGET',
          `Unterfeld-Typ „${sf.widget}" ist hier nicht erlaubt.`))
      }
      if (sf.widget === 'server_stamped' && sf.value !== 'actor' && sf.value !== 'now') {
        out.push(err(`${p}.item.${j}.value`, anchor, 'INVALID',
          'Systemstempel braucht die Quelle „actor" oder „now".'))
      }
    })

    if (f.visibility?.confidential && f.visibility.visibleToGroups.length === 0) {
      out.push(err(`${p}.visibility`, anchor, 'REQUIRED',
        'Vertrauliche Felder brauchen mindestens eine berechtigte Fachabteilung.'))
    }
    f.visibility?.visibleToGroups.forEach((g) => {
      if (knownGroupIds && !knownGroupIds.has(g)) {
        out.push(warn(`${p}.visibility`, anchor, 'UNKNOWN_GROUP',
          `Unbekannte Fachabteilung „${g}" in der Sichtbarkeit.`))
      }
    })
    if (f.computed && !catalog.has(f.computed.from)) {
      out.push(err(`${p}.computed`, anchor, 'UNKNOWN_REF',
        `Abgeleitet aus „${f.computed.from}" – dieses Feld gibt es nicht.`))
    }

    // ── Vom Server vergebene Nummer (widget=server_generated + assign) ──
    if (f.widget === 'server_generated' && !f.assign) {
      out.push(err(`${p}.assign`, anchor, 'REQUIRED',
        'Ein vom System vergebener Wert braucht die Angabe, woher die Nummer kommt.'))
    }
    if (f.assign) {
      if (f.widget !== 'server_generated') {
        out.push(warn(`${p}.assign`, anchor, 'INVALID',
          `Die Nummernvergabe wirkt nur beim Feldtyp „${WIDGET_LABEL.server_generated}" – `
          + 'bei diesem Feldtyp bleibt sie wirkungslos.'))
      }
      if (f.assign.action !== 'assign_sequence') {
        out.push(err(`${p}.assign.action`, anchor, 'UNSUPPORTED',
          `„${f.assign.action}" ist keine Vergabe-Aktion (erlaubt: Nummer aus Nummernkreis).`))
      }
      if (!f.assign.counter) {
        out.push(err(`${p}.assign.counter`, anchor, 'REQUIRED',
          'Bitte den Nummernkreis angeben, aus dem die Nummer kommt.'))
      } else if (!SEQUENCE_COUNTERS.includes(f.assign.counter)) {
        // Der Server prüft den Namen NICHT – die Vergabe scheitert erst beim
        // Phasenabschluss. Darum warnen statt blockieren.
        out.push(warn(`${p}.assign.counter`, anchor, 'UNKNOWN_COUNTER',
          `Nummernkreis „${f.assign.counter}" ist der Laufzeit unbekannt – die Vergabe `
          + `bricht später ab. Bekannt: ${SEQUENCE_COUNTERS.join(', ')}.`))
      }
      if (!f.assign.companyRef) {
        out.push(warn(`${p}.assign.companyRef`, anchor, 'REQUIRED',
          'Ohne Firmen-Feld gibt es keinen Nummernkreis – die Vergabe bricht beim '
          + 'Abschluss der Phase ab.'))
      } else if (!catalog.has(f.assign.companyRef)) {
        out.push(warn(`${p}.assign.companyRef`, anchor, 'UNKNOWN_REF',
          `Firmen-Feld „${f.assign.companyRef}" ist nicht im Katalog.`))
      }
    }
    const c = f.constraints
    if (c?.pattern) {
      try { new RegExp(c.pattern) } catch {
        out.push(err(`${p}.constraints.pattern`, anchor, 'INVALID', 'Ungültiges Muster (Regex).'))
      }
    }
    if (c && c.minLength != null && c.maxLength != null && c.minLength > c.maxLength) {
      out.push(err(`${p}.constraints`, anchor, 'INVALID', 'Mindestlänge größer als Maximallänge.'))
    }
    if (c && c.min != null && c.max != null && c.min > c.max) {
      out.push(err(`${p}.constraints`, anchor, 'INVALID', 'Minimum größer als Maximum.'))
    }
    if (c && c.minDate && c.maxDate && c.minDate > c.maxDate) {
      out.push(err(`${p}.constraints`, anchor, 'INVALID', 'Von-Datum liegt nach dem Bis-Datum.'))
    }
  })

  // ── Phasen ──
  if (d.phases.length === 0) {
    out.push(err('phases', TOP, 'REQUIRED', 'Der Prozess braucht mindestens eine Phase.'))
  }
  const starts = d.phases.filter((p) => p.kind === 'start')
  if (d.phases.length && starts.length !== 1) {
    out.push(err('phases', TOP, 'MISSING_START',
      'Der Prozess braucht genau eine Start-Phase.'))
  }
  if (d.phases.length && d.phases[0].kind !== 'start') {
    out.push(err('phases.0', 'pe-phase-0', 'START_NOT_FIRST',
      'Die Start-Phase muss die erste Phase sein.'))
  }

  const seenPhaseKeys = new Set<string>()
  const autoIds = new Map<string, number>()
  const countAuto = (id: string) => autoIds.set(id, (autoIds.get(id) ?? 0) + 1)
  d.automations.forEach((a) => countAuto(a.id))

  const roComputed = new Set(d.fields.filter((f) => f.computed && !f.overridable).map((f) => f.key))
  /** Felder, die ausschließlich der Server füllt – in keiner Phase beschreibbar. */
  const serverAssigned = new Set(d.fields.filter((f) => f.widget === 'server_generated')
    .map((f) => f.key))
  const phaseKeys = d.phases.map((ph) => ph.key)

  // Ein server_generated-Feld wird beim Abschluss der ERSTEN Phase vergeben, die
  // es führt. Bindet es keine Phase ein, bekommt es nie eine Nummer.
  serverAssigned.forEach((k) => {
    if (!d.phases.some((ph) => ph.fields.some((fr) => fr.ref === k))) {
      const idx = d.fields.findIndex((f) => f.key === k)
      out.push(warn(`fields.${idx}`, `pe-catalog-${idx}`, 'NEVER_ASSIGNED',
        `„${k}" wird vom System vergeben, ist aber in keiner Phase eingebunden – `
        + 'damit bekommt es nie eine Nummer.'))
    }
  })

  d.phases.forEach((ph, i) => {
    const anchor = `pe-phase-${i}`
    const p = `phases.${i}`
    if (!ph.key) out.push(err(`${p}.key`, anchor, 'REQUIRED', 'Phase braucht einen Schlüssel.'))
    else if (!isValidPhaseKey(ph.key)) {
      out.push(err(`${p}.key`, anchor, 'INVALID_KEY',
        `Phasen-Schlüssel „${ph.key}": nur a–z, 0–9 und „_".`))
    } else if (seenPhaseKeys.has(ph.key)) {
      out.push(err(`${p}.key`, anchor, 'DUPLICATE_KEY', `Doppelter Phasen-Schlüssel „${ph.key}".`))
    }
    seenPhaseKeys.add(ph.key)

    if (!PHASE_KINDS.includes(ph.kind)) {
      out.push(err(`${p}.kind`, anchor, 'UNSUPPORTED', `Phasen-Art „${ph.kind}" ist nicht verfügbar.`))
    }
    if (!PHASE_VIEWS.includes(ph.view)) {
      out.push(err(`${p}.view`, anchor, 'UNSUPPORTED', `Ansicht „${ph.view}" ist nicht verfügbar.`))
    }
    if (ph.enterStatus && !ENTER_STATUS.includes(ph.enterStatus)) {
      out.push(err(`${p}.enterStatus`, anchor, 'UNSUPPORTED',
        `Status „${ph.enterStatus}" ist hier nicht erlaubt (terminale Status sperren das Ticket).`))
    }
    if (ph.responsibility.resetOnDescriptionChange) {
      out.push(err(`${p}.responsibility`, anchor, 'UNSUPPORTED',
        'Zurücksetzen bei Änderung ist noch nicht umgesetzt.'))
    }

    // ── Freigabe-Phase: Art, Ansicht und Block gehören zusammen ──
    const ap = ph.approval
    if (ph.kind === 'approval' && !ap) {
      out.push(err(`${p}.approval`, anchor, 'REQUIRED',
        'Eine Freigabe-Phase braucht eine Frage und das Verhalten bei „Nein".'))
    }
    if (ph.kind !== 'approval' && ap) {
      out.push(err(`${p}.approval`, anchor, 'INVALID',
        'Freigabe-Angaben sind nur bei der Phasen-Art „Freigabe" erlaubt.'))
    }
    if (ph.view === 'approval' && ph.kind !== 'approval') {
      out.push(err(`${p}.view`, anchor, 'INVALID',
        'Die Ansicht „Freigabe" passt nur zur Phasen-Art „Freigabe".'))
    }
    if (ap) {
      if (!ap.question?.trim()) {
        out.push(err(`${p}.approval.question`, anchor, 'REQUIRED',
          'Ohne Frage weiß niemand, worüber entschieden wird.'))
      }
      if (!isValidDuration(ap.linkMaxAge)) {
        out.push(err(`${p}.approval.linkMaxAge`, anchor, 'INVALID',
          `Ungültige Gültigkeit „${ap.linkMaxAge}" (z. B. P7D, PT12H; Monate/Jahre `
          + 'nicht möglich).'))
      }
      for (const [feld, lbl] of [[ap.decisionField, 'Entscheidungs-Feld'],
        [ap.reasonField, 'Begründungs-Feld']] as const) {
        if (feld && !catalog.has(feld)) {
          out.push(err(`${p}.approval`, anchor, 'UNKNOWN_REF',
            `${lbl} „${feld}" ist nicht im Katalog.`))
        }
      }
      // Mail-Vorlage: jede {{variable}} muss ein Katalog-Feld sein (Spezial-Vars
      // title/id sind immer erlaubt). Sonst bliebe in der Mail eine leere Stelle.
      for (const ref of mailFieldRefs(ap.emailBody)) {
        if (!catalog.has(ref)) {
          out.push(err(`${p}.approval.emailBody`, anchor, 'UNKNOWN_REF',
            `Mail-Variable „{{${ref}}}" verweist auf ein Feld, das es nicht gibt.`))
        }
      }
      if (!isValidOnReject(ap.onReject)) {
        out.push(err(`${p}.approval.onReject`, anchor, 'INVALID',
          `Verhalten bei „Nein" ist unbekannt: „${ap.onReject}".`))
      } else {
        const ziel = backToTarget(ap.onReject)
        if (ziel && !phaseKeys.includes(ziel)) {
          out.push(err(`${p}.approval.onReject`, anchor, 'UNKNOWN_REF',
            `Rücksprung auf „${ziel}" – diese Phase gibt es nicht.`))
        } else if (ziel && phaseKeys.indexOf(ziel) >= i) {
          // Ein Sprung nach vorn (oder auf sich selbst) würde Arbeit überspringen.
          out.push(err(`${p}.approval.onReject`, anchor, 'INVALID',
            `Rücksprung auf „${ziel}": das Ziel muss VOR dieser Phase liegen.`))
        }
      }
    }

    const r = ph.responsibility
    if (!RESPONSIBILITY_KINDS.includes(r.kind)) {
      out.push(err(`${p}.responsibility.kind`, anchor, 'UNSUPPORTED',
        `Zuständigkeit „${r.kind}" ist nicht verfügbar.`))
    }
    if (r.kind === 'group' && !r.group) {
      out.push(err(`${p}.responsibility.group`, anchor, 'REQUIRED', 'Bitte eine Fachabteilung wählen.'))
    }
    if (r.kind === 'user' && !r.user) {
      out.push(err(`${p}.responsibility.user`, anchor, 'REQUIRED', 'Bitte eine Person wählen.'))
    }
    // Zuständigkeit aus einem FELD: die Quelle muss existieren UND vom richtigen
    // Typ sein – sonst stünde dort später irgendein Text statt einer Kennung.
    // Ohne gültige Quelle hätte die Phase niemanden; der Server lehnt sie ab.
    const AUS_FELD = {
      assignable: { widget: 'user' as const, was: 'Personen-Feld' },
      group_from_field: { widget: 'group' as const, was: 'Fachabteilungs-Feld' },
    }
    const erwartet = r.kind === 'assignable' || r.kind === 'group_from_field'
      ? AUS_FELD[r.kind] : null
    if (erwartet) {
      const src = d.fields.find((f) => f.key === r.fromField)
      if (!r.fromField) {
        out.push(err(`${p}.responsibility.fromField`, anchor, 'REQUIRED',
          `Bitte das ${erwartet.was} angeben, aus dem die Zuständigkeit kommt.`))
      } else if (!src) {
        out.push(err(`${p}.responsibility.fromField`, anchor, 'UNKNOWN_REF',
          `Feld „${r.fromField}" ist nicht im Katalog.`))
      } else if (src.widget !== erwartet.widget) {
        out.push(err(`${p}.responsibility.fromField`, anchor, 'INVALID',
          `„${r.fromField}" muss ein ${erwartet.was} sein `
          + `(aktuell „${WIDGET_LABEL[src.widget] ?? src.widget}").`))
      }
    }
    if (r.kind === 'departments' && r.rule.length === 0) {
      out.push(err(`${p}.responsibility.rule`, anchor, 'REQUIRED',
        'Mindestens eine Fachabteilung angeben.'))
    }
    r.rule.forEach((dr, j) => {
      if (!dr.group) {
        out.push(err(`${p}.responsibility.rule.${j}`, anchor, 'REQUIRED', 'Fachabteilung fehlt.'))
      } else if (knownGroupIds && !knownGroupIds.has(dr.group)) {
        out.push(warn(`${p}.responsibility.rule.${j}`, anchor, 'UNKNOWN_GROUP',
          `Unbekannte Fachabteilung „${dr.group}".`))
      }
      if (dr.when && !isWellFormedCondition(dr.when)) {
        out.push(err(`${p}.responsibility.rule.${j}.when`, anchor, 'INVALID_DSL',
          'Bedingung ist nicht wohlgeformt.'))
      }
      dslRefs(dr.when).forEach((ref) => {
        if (!catalog.has(ref)) {
          out.push(err(`${p}.responsibility.rule.${j}.when`, anchor, 'UNKNOWN_REF',
            `Bedingung verweist auf unbekanntes Feld „${ref}".`))
        }
      })
    })
    if (knownGroupIds && r.kind === 'group' && r.group && !knownGroupIds.has(r.group)) {
      out.push(warn(`${p}.responsibility.group`, anchor, 'UNKNOWN_GROUP',
        `Unbekannte Fachabteilung „${r.group}".`))
    }

    // Felder der Phase
    const seenRefs = new Set<string>()
    ph.fields.forEach((fr, j) => {
      const fp = `${p}.fields.${j}`
      const fanchor = `pe-phase-${i}-field-${j}`
      if (!catalog.has(fr.ref)) {
        out.push(err(`${fp}.ref`, fanchor, 'UNKNOWN_REF',
          `Feld „${fr.ref}" ist nicht im Katalog.`))
      }
      if (seenRefs.has(fr.ref)) {
        out.push(warn(`${fp}.ref`, fanchor, 'DUPLICATE_REF',
          `Feld „${fr.ref}" ist in dieser Phase mehrfach eingebunden.`))
      }
      seenRefs.add(fr.ref)
      const beschreibbar = fr.mode === 'editable' || fr.mode === 'append_only'
      if (roComputed.has(fr.ref) && beschreibbar) {
        out.push(err(`${fp}.mode`, fanchor, 'COMPUTED_NOT_EDITABLE',
          `„${fr.ref}" wird berechnet und darf nicht bearbeitbar sein.`))
      }
      if (serverAssigned.has(fr.ref) && beschreibbar) {
        out.push(err(`${fp}.mode`, fanchor, 'SERVER_FIELD_NOT_EDITABLE',
          `„${fr.ref}" wird vom System vergeben und darf nicht bearbeitbar sein `
          + '(nur „Nur lesen" oder „Ausgeblendet").'))
      }
      for (const [cond, label] of [[fr.requiredWhen, 'Pflicht-Bedingung'],
        [fr.visibleWhen, 'Anzeige-Bedingung']] as const) {
        if (!cond) continue
        if (!isWellFormedCondition(cond)) {
          out.push(err(fp, fanchor, 'INVALID_DSL', `${label} ist nicht wohlgeformt.`))
        }
        dslRefs(cond).forEach((ref) => {
          if (!catalog.has(ref)) {
            out.push(err(fp, fanchor, 'UNKNOWN_REF',
              `${label} verweist auf unbekanntes Feld „${ref}".`))
          }
        })
      }
    })

    // Layout: darf nur Felder dieser Phase platzieren, jedes höchstens einmal.
    // Nicht platzierte Felder sind kein Fehler (sie landen im Sammel-Abschnitt),
    // aber ein Hinweis – sonst wundert sich später jemand über die Reihenfolge.
    const phaseRefs = new Set(ph.fields.map((fr) => fr.ref))
    const placed = new Set<string>()
    ph.layout.forEach((sec, si) => {
      const lanchor = `pe-layout-${si}`
      sec.items.forEach((it, ii) => {
        const lp = `${p}.layout.${si}.items.${ii}`
        if (it.type === 'field') {
          if (!phaseRefs.has(it.ref)) {
            out.push(err(lp, lanchor, 'UNKNOWN_REF',
              `„${it.ref}" ist in dieser Phase nicht eingebunden.`))
          }
          if (placed.has(it.ref)) {
            out.push(err(lp, lanchor, 'DUPLICATE_REF',
              `„${it.ref}" ist mehrfach platziert.`))
          }
          placed.add(it.ref)
        } else if (it.type === 'note' && !it.text.trim()) {
          out.push(warn(lp, lanchor, 'EMPTY', 'Leere Hinweisbox.'))
        } else if (it.type === 'heading' && !it.text.trim()) {
          out.push(warn(lp, lanchor, 'EMPTY', 'Zwischen-Überschrift ohne Text.'))
        }
      })
    })
    if (ph.layout.length) {
      const missing = [...phaseRefs].filter((r) => !placed.has(r))
      if (missing.length) {
        out.push(warn(`${p}.layout`, `pe-phase-${i}`, 'UNPLACED',
          `${missing.length} Feld(er) sind nicht im Layout platziert und erscheinen `
          + `hinten unter „Weitere Angaben": ${missing.slice(0, 5).join(', ')}`
          + (missing.length > 5 ? ' …' : '')))
      }
    }

    // Phasen-Constraints
    ph.constraints.forEach((c, j) => {
      const cp = `${p}.constraints.${j}`
      if (!c.message?.trim()) {
        out.push(err(cp, anchor, 'REQUIRED', 'Regel braucht eine Meldung.'))
      }
      if (!isWellFormedCondition(c.when)) {
        out.push(err(cp, anchor, 'INVALID_DSL', 'Regel-Bedingung ist nicht wohlgeformt.'))
      }
      dslRefs(c.when).forEach((ref) => {
        if (!catalog.has(ref)) {
          out.push(err(cp, anchor, 'UNKNOWN_REF', `Regel verweist auf unbekanntes Feld „${ref}".`))
        }
      })
    })

    ph.automations.forEach((a) => countAuto(a.id))
  })

  // ── Automationen (prozessweit + je Phase) ──
  const allAutos = [
    ...d.automations.map((a, i) => ({ a, path: `automations.${i}`, anchor: `pe-automation-${i}` })),
    ...d.phases.flatMap((ph, i) => ph.automations.map((a, j) => ({
      a, path: `phases.${i}.automations.${j}`, anchor: `pe-phase-${i}` }))),
  ]
  allAutos.forEach(({ a, path, anchor }) => {
    if (!a.id?.trim()) out.push(err(`${path}.id`, anchor, 'REQUIRED', 'Automation braucht eine ID.'))
    else if ((autoIds.get(a.id) ?? 0) > 1) {
      out.push(err(`${path}.id`, anchor, 'DUPLICATE_KEY', `Doppelte Automations-ID „${a.id}".`))
    }
    const t = a.trigger
    if (t.type === 'timer') {
      if (!t.after) out.push(err(`${path}.trigger.after`, anchor, 'REQUIRED', 'Zeitpunkt fehlt.'))
      else if (!isValidDuration(t.after)) {
        out.push(err(`${path}.trigger.after`, anchor, 'INVALID',
          `Ungültige Dauer „${t.after}" (z.B. P7D, PT12H; Monate/Jahre nicht möglich).`))
      }
      if (t.repeat && !isValidDuration(t.repeat)) {
        out.push(err(`${path}.trigger.repeat`, anchor, 'INVALID',
          `Ungültige Wiederholung „${t.repeat}".`))
      }
    } else if (t.after || t.repeat) {
      out.push(err(`${path}.trigger`, anchor, 'INVALID',
        'Zeitangaben sind nur bei zeitgesteuerten Automationen erlaubt.'))
    }
    if (t.type === 'on_field_change') {
      if (!t.field) out.push(err(`${path}.trigger.field`, anchor, 'REQUIRED', 'Feld fehlt.'))
      else if (!catalog.has(t.field)) {
        out.push(err(`${path}.trigger.field`, anchor, 'UNKNOWN_REF',
          `Unbekanntes Feld „${t.field}".`))
      }
    }
    if (a.guard) {
      if (!isWellFormedCondition(a.guard)) {
        out.push(err(`${path}.guard`, anchor, 'INVALID_DSL', 'Bedingung ist nicht wohlgeformt.'))
      }
      dslRefs(a.guard).forEach((ref) => {
        if (!catalog.has(ref)) {
          out.push(err(`${path}.guard`, anchor, 'UNKNOWN_REF',
            `Bedingung verweist auf unbekanntes Feld „${ref}".`))
        }
      })
    }
    const ac = a.action
    if (!ACTION_TYPES.includes(ac.type)) {
      out.push(err(`${path}.action.type`, anchor, 'UNSUPPORTED',
        `Aktion „${ac.type}" ist nicht verfügbar.`))
    }
    if ((ac.type === 'notify' || ac.type === 'escalate')) {
      if (!ac.to) out.push(err(`${path}.action.to`, anchor, 'REQUIRED', 'Empfänger fehlt.'))
      else if (!RECIPIENTS.includes(ac.to) && !ac.to.startsWith('group:')) {
        out.push(err(`${path}.action.to`, anchor, 'INVALID', `Unbekanntes Ziel „${ac.to}".`))
      } else if (knownGroupIds && ac.to.startsWith('group:')
                 && !knownGroupIds.has(ac.to.slice(6))) {
        out.push(warn(`${path}.action.to`, anchor, 'UNKNOWN_GROUP',
          `Unbekannte Fachabteilung „${ac.to.slice(6)}".`))
      }
    }
    if (ac.type === 'set_field') {
      if (!ac.field) out.push(err(`${path}.action.field`, anchor, 'REQUIRED', 'Feld fehlt.'))
      else if (!catalog.has(ac.field)) {
        out.push(err(`${path}.action.field`, anchor, 'UNKNOWN_REF',
          `Unbekanntes Feld „${ac.field}".`))
      }
      if (ac.value === null || ac.value === undefined) {
        out.push(err(`${path}.action.value`, anchor, 'REQUIRED', 'Wert fehlt.'))
      }
    }
    if (ac.type === 'set_status' && !ENTER_STATUS.includes(String(ac.value))) {
      out.push(err(`${path}.action.value`, anchor, 'INVALID',
        'Nur nicht-terminale Status sind erlaubt.'))
    }
    if (ac.type === 'set_priority' && !PRIORITIES.includes(String(ac.value))) {
      out.push(err(`${path}.action.value`, anchor, 'INVALID', 'Unbekannte Priorität.'))
    }
    if (ac.type === 'assign_sequence') {
      if (!ac.counter) {
        out.push(err(`${path}.action.counter`, anchor, 'REQUIRED', 'Nummernkreis fehlt.'))
      } else if (!SEQUENCE_COUNTERS.includes(ac.counter)) {
        out.push(warn(`${path}.action.counter`, anchor, 'UNKNOWN_COUNTER',
          `Nummernkreis „${ac.counter}" ist der Laufzeit unbekannt `
          + `(bekannt: ${SEQUENCE_COUNTERS.join(', ')}).`))
      }
      if (!ac.field) {
        out.push(err(`${path}.action.field`, anchor, 'REQUIRED',
          'Feld fehlt – ohne Ziel wüsste niemand, wohin die Nummer geschrieben wird.'))
      } else if (!catalog.has(ac.field)) {
        out.push(err(`${path}.action.field`, anchor, 'UNKNOWN_REF',
          `Unbekanntes Feld „${ac.field}".`))
      }
    }
  })

  return out
}

export function errorCount(issues: ProcessIssue[]): number {
  return issues.filter((i) => i.severity === 'error').length
}
