/**
 * Umbenennen eines Feld-Schlüssels – strukturell, nicht per Text-Ersetzung.
 *
 * Angefasst werden ausschließlich echte Referenzpositionen:
 *   fields[].key, fields[].computed.from,
 *   phases[].fields[].ref,
 *   Trigger.field / Action.field,
 *   die Feld-Referenz in DSL-Knoten (requiredWhen, visibleWhen, when, guard,
 *   phases[].constraints[].when).
 *
 * NICHT angefasst: Options-Werte, Labels, Meldungen, Phasen-Schlüssel,
 * Prozess-Key, Action.value. Ein früheres blindes JSON-Replace hat genau die
 * still mit umbenannt (Phasen- und Feld-Alphabet überschneiden sich).
 */
import type { Condition, ProcessDefinition } from '@/types/process'

/** Ersetzt die Feld-Referenz in einem DSL-Knoten (rekursiv, unverändert kopiert). */
export function renameRefsInCondition(
  cond: Condition | null, from: string, to: string,
): Condition | null {
  if (!cond || typeof cond !== 'object' || Array.isArray(cond)) return cond
  const keys = Object.keys(cond)
  if (keys.length !== 1) return cond
  const op = keys[0]
  const arg = (cond as any)[op]

  if (op === '==' || op === '!=' || op === 'in') {
    if (Array.isArray(arg) && typeof arg[0] === 'string') {
      // Nur arg[0] ist die Feld-Referenz; arg[1] ist ein Wert und bleibt.
      return { [op]: [arg[0] === from ? to : arg[0], arg[1]] }
    }
    return cond
  }
  if (op === 'truthy') {
    return typeof arg === 'string' ? { truthy: arg === from ? to : arg } : cond
  }
  if (op === 'and' || op === 'or') {
    return Array.isArray(arg)
      ? { [op]: arg.map((c) => renameRefsInCondition(c, from, to)) }
      : cond
  }
  if (op === 'not') return { not: renameRefsInCondition(arg, from, to) }
  return cond
}

const ref = (v: string | null, from: string, to: string) => (v === from ? to : v)

export function renameRefsInDefinition(
  defn: ProcessDefinition, from: string, to: string,
): ProcessDefinition {
  return {
    ...defn,
    fields: defn.fields.map((f) => ({
      ...f,
      key: f.key === from ? to : f.key,
      computed: f.computed ? { from: ref(f.computed.from, from, to) as string } : null,
      // Nummernvergabe: das Firmen-Feld ist eine echte Referenzposition.
      assign: f.assign ? { ...f.assign, companyRef: ref(f.assign.companyRef, from, to) } : null,
    })),
    automations: defn.automations.map((a) => ({
      ...a,
      trigger: { ...a.trigger, field: ref(a.trigger.field, from, to) },
      guard: renameRefsInCondition(a.guard, from, to),
      action: { ...a.action, field: ref(a.action.field, from, to) },
    })),
    phases: defn.phases.map((p) => ({
      ...p,
      fields: p.fields.map((fr) => ({
        ...fr,
        ref: fr.ref === from ? to : fr.ref,
        requiredWhen: renameRefsInCondition(fr.requiredWhen, from, to),
        visibleWhen: renameRefsInCondition(fr.visibleWhen, from, to),
      })),
      constraints: p.constraints.map((c) => ({
        ...c,
        when: (renameRefsInCondition(c.when, from, to) ?? {}) as Condition,
      })),
      responsibility: {
        ...p.responsibility,
        // Quellfeld bei kind='assignable' bzw. 'group_from_field'.
        fromField: ref(p.responsibility.fromField, from, to),
        rule: p.responsibility.rule.map((r) => ({
          ...r,
          when: renameRefsInCondition(r.when, from, to),
        })),
      },
      // Freigabe: Entscheidung und Begründung zeigen auf Katalog-Felder.
      approval: p.approval ? {
        ...p.approval,
        decisionField: ref(p.approval.decisionField, from, to),
        reasonField: ref(p.approval.reasonField, from, to),
      } : null,
      automations: p.automations.map((a) => ({
        ...a,
        trigger: { ...a.trigger, field: ref(a.trigger.field, from, to) },
        guard: renameRefsInCondition(a.guard, from, to),
        action: { ...a.action, field: ref(a.action.field, from, to) },
      })),
    })),
  }
}
