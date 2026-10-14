/**
 * Ablauf-Graph aus einer Prozess-Definition ableiten – für das Diagramm im Editor.
 *
 * Bewusst als reines Modul (ohne Vue), damit es ohne DOM testbar ist. Spiegelt die
 * Flussregeln der Laufzeit (backend/services/process_runtime + process_engine):
 *   • Weiterschalten ist POSITIONSBASIERT – die nächste Phase im Array (kein „next").
 *   • Freigabe-Phase: approve → nächste Phase; onReject='reject' → Terminal „Abgelehnt";
 *     onReject='back_to:X' → Rücksprung auf eine FRÜHERE Phase X.
 *   • on_enter + auto_advance = Phase wird (ggf. bedingt per guard) übersprungen.
 *   • review(departments): EIN Knoten mit mehreren (ggf. bedingten) Abteilungs-Lanes.
 *   • Hinter der letzten Phase liegt das Terminal „Archiviert".
 */
import type { PhaseDef, PhaseKind, ProcessDefinition } from '@/types/process'
import { backToTarget } from '@/lib/processSchema'

export const TERMINAL_ARCHIVED = '__archived__'
export const TERMINAL_REJECTED = '__rejected__'

export type FlowEdgeKind = 'advance' | 'approve' | 'reject' | 'send_back' | 'auto'

export interface FlowEdge {
  from: string
  to: string
  kind: FlowEdgeKind
  label: string
  /** Kante greift nur unter einer Bedingung (z. B. guard eines auto_advance). */
  conditional: boolean
}

export interface FlowDept {
  group: string
  required: boolean
  /** Abteilung ist nur unter einer Bedingung (DepartmentRule.when) beteiligt. */
  conditional: boolean
}

export interface FlowNode {
  id: string
  index: number
  label: string
  kind: PhaseKind
  /** on_enter + auto_advance → Pass-Through (wird automatisch weitergeschaltet). */
  auto: boolean
  /** Das auto_advance hat einen guard → wird nur BEDINGT übersprungen. */
  autoConditional: boolean
  approval: boolean
  departments: FlowDept[]
}

export interface FlowModel {
  nodes: FlowNode[]
  edges: FlowEdge[]
  hasArchived: boolean
  hasRejected: boolean
}

/** on_enter-auto_advance einer Phase finden (phasen-lokal). */
function onEnterAutoAdvance(phase: PhaseDef): { auto: boolean; guard: boolean } {
  for (const a of phase.automations || []) {
    if (a.trigger?.type === 'on_enter' && a.action?.type === 'auto_advance') {
      return { auto: true, guard: a.guard != null }
    }
  }
  return { auto: false, guard: false }
}

export function buildFlowModel(defn: ProcessDefinition | null | undefined): FlowModel {
  const phases: PhaseDef[] = defn?.phases ?? []
  const nodes: FlowNode[] = []
  const edges: FlowEdge[] = []
  let hasArchived = false
  let hasRejected = false

  const indexOf = (key: string) => phases.findIndex((p) => p.key === key)

  phases.forEach((p, i) => {
    const aa = onEnterAutoAdvance(p)
    const departments: FlowDept[] = p.responsibility?.kind === 'departments'
      ? (p.responsibility.rule || []).map((r) => ({
          group: r.group, required: r.required, conditional: r.when != null }))
      : []
    nodes.push({
      id: p.key,
      index: i,
      label: p.label || p.key,
      kind: p.kind,
      auto: aa.auto,
      autoConditional: aa.auto && aa.guard,
      approval: p.kind === 'approval' && !!p.approval,
      departments,
    })
  })

  const last = phases.length - 1
  phases.forEach((p, i) => {
    const nextId = i < last ? phases[i + 1].key : TERMINAL_ARCHIVED
    if (i === last) hasArchived = true

    if (p.kind === 'approval' && p.approval) {
      edges.push({ from: p.key, to: nextId, kind: 'approve',
        label: p.approval.approveLabel || 'Freigeben', conditional: false })
      const target = backToTarget(p.approval.onReject)
      if (target && indexOf(target) >= 0) {
        edges.push({ from: p.key, to: target, kind: 'send_back',
          label: p.approval.rejectLabel || 'Nachbesserung', conditional: false })
      } else {
        edges.push({ from: p.key, to: TERMINAL_REJECTED, kind: 'reject',
          label: p.approval.rejectLabel || 'Ablehnen', conditional: false })
        hasRejected = true
      }
    } else {
      const auto = nodes[i].auto
      edges.push({ from: p.key, to: nextId, kind: auto ? 'auto' : 'advance',
        label: auto ? 'automatisch' : (p.advanceLabel || 'weiter'),
        conditional: nodes[i].autoConditional })
    }
  })

  return { nodes, edges, hasArchived, hasRejected }
}
