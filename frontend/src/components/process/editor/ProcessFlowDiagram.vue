<script setup lang="ts">
/**
 * Ablauf-Diagramm einer Prozess-Definition (neuer Tab im Editor).
 *
 * Zeigt die Phasen als vertikale Kette; die echten Übergänge (Weiter, Freigabe,
 * Ablehnung, Rücksprung, automatischer Übersprung, Abteilungs-Fan-out) werden als
 * farbige Pfeile in einem SVG-Overlay gezeichnet – die Positionen werden nach dem
 * Rendern aus dem DOM gemessen. Klick auf eine Phase → Detail-/Sichtbarkeits-Panel.
 *
 * Bewusst ohne Graph-Bibliothek (Lean-Deps-Linie, Muster wie ProcessTimeline.vue):
 * der Graph-Aufbau steckt im reinen, getesteten Modul lib/processFlow.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FieldDef, PhaseDef, ProcessDefinition } from '@/types/process'
import { PHASE_KIND_LABEL, PHASE_KIND_META, backToTarget } from '@/lib/processSchema'
import { resolveResponsibility, responsibilityText } from '@/lib/processSim'
import {
  buildFlowModel, TERMINAL_ARCHIVED, TERMINAL_REJECTED,
  type FlowEdgeKind,
} from '@/lib/processFlow'

const props = defineProps<{
  definition: ProcessDefinition | null
  groups?: { id: string; name: string }[]
}>()
const emit = defineEmits<{ 'select-phase': [index: number] }>()

const model = computed(() => buildFlowModel(props.definition))
const phases = computed<PhaseDef[]>(() => props.definition?.phases ?? [])
const fieldMap = computed(() => new Map((props.definition?.fields ?? []).map((f) => [f.key, f])))
const groupsById = computed(() => new Map((props.groups ?? []).map((g) => [g.id, g.name])))
const groupName = (id: string) => groupsById.value.get(id) ?? id

// ── Kanten-Optik ────────────────────────────────────────────────────────────
const EDGE: Record<FlowEdgeKind, { stroke: string; legend: string }> = {
  advance: { stroke: '#94a3b8', legend: 'Weiter' },
  approve: { stroke: '#10b981', legend: 'Freigabe (Ja)' },
  reject: { stroke: '#ef4444', legend: 'Ablehnung' },
  send_back: { stroke: '#f59e0b', legend: 'Rücksprung' },
  auto: { stroke: '#0ea5e9', legend: 'Automatisch' },
}
const EDGE_KINDS = Object.keys(EDGE) as FlowEdgeKind[]

// ── Auswahl ───────────────────────────────────────────────────────────────────
const selected = ref<number | null>(null)
watch(() => props.definition?.key, () => { selected.value = phases.value.length ? 0 : null },
  { immediate: true })
const selectedPhase = computed<PhaseDef | null>(() =>
  selected.value != null ? phases.value[selected.value] ?? null : null)
const selectedKey = computed(() => selectedPhase.value?.key ?? null)

function select(i: number) { selected.value = i }

// ── Geometrie-Messung ───────────────────────────────────────────────────────
const containerRef = ref<HTMLElement | null>(null)
const nodeEls = new Map<string, HTMLElement>()
const reg = (id: string, el: unknown) => {
  if (el) nodeEls.set(id, el as HTMLElement)
  else nodeEls.delete(id)
}
interface Box { top: number; bottom: number; cy: number; left: number; right: number; cx: number }
const geo = ref<Record<string, Box>>({})
const size = ref<{ w: number; h: number }>({ w: 0, h: 0 })
const GUT = 20 // Rinne links/rechts für gebogene Kanten (px)

function recompute() {
  const c = containerRef.value
  if (!c) return
  const box: Record<string, Box> = {}
  for (const [id, el] of nodeEls) {
    box[id] = {
      top: el.offsetTop, bottom: el.offsetTop + el.offsetHeight,
      cy: el.offsetTop + el.offsetHeight / 2,
      left: el.offsetLeft, right: el.offsetLeft + el.offsetWidth,
      cx: el.offsetLeft + el.offsetWidth / 2,
    }
  }
  geo.value = box
  size.value = { w: c.clientWidth, h: c.scrollHeight }
}
const scheduleRecompute = () => nextTick(() => requestAnimationFrame(recompute))

let ro: ResizeObserver | null = null
onMounted(() => {
  scheduleRecompute()
  ro = new ResizeObserver(() => recompute())
  if (containerRef.value) ro.observe(containerRef.value)
})
onBeforeUnmount(() => { ro?.disconnect(); ro = null })
watch(() => props.definition, scheduleRecompute, { deep: true })

// ── Kanten → SVG-Pfade ────────────────────────────────────────────────────────
interface RenderEdge {
  key: string; d: string; stroke: string; dash: string; marker: string
  label: string; conditional: boolean; lx: number; ly: number; strong: boolean
}
const renderEdges = computed<RenderEdge[]>(() => {
  const g = geo.value
  const w = size.value.w
  const sel = selectedKey.value
  const out: RenderEdge[] = []
  model.value.edges.forEach((e, i) => {
    const a = g[e.from]; const b = g[e.to]
    if (!a || !b) return
    let d = ''; let lx = 0; let ly = 0
    if (e.kind === 'send_back') {
      const sx = a.left; const tx = b.left; const gx = GUT
      d = `M ${sx} ${a.cy} C ${gx} ${a.cy} ${gx} ${b.cy} ${tx} ${b.cy}`
      lx = gx + 2; ly = (a.cy + b.cy) / 2
    } else if (e.kind === 'reject') {
      const sx = a.right; const tx = b.right; const gx = Math.max(w - GUT, a.right + 10)
      d = `M ${sx} ${a.cy} C ${gx} ${a.cy} ${gx} ${b.cy} ${tx} ${b.cy}`
      lx = gx - 2; ly = (a.cy + b.cy) / 2
    } else {
      const sx = a.cx; const tx = b.cx; const my = (a.bottom + b.top) / 2
      d = `M ${sx} ${a.bottom} C ${sx} ${my} ${tx} ${my} ${tx} ${b.top}`
      lx = (sx + tx) / 2; ly = my
    }
    const strong = sel != null && (e.from === sel || e.to === sel)
    out.push({
      key: `${e.from}->${e.to}:${e.kind}:${i}`, d, stroke: EDGE[e.kind].stroke,
      dash: e.kind === 'auto' ? '6 5' : '', marker: `url(#arw-${e.kind})`,
      label: e.label, conditional: e.conditional, lx, ly, strong,
    })
  })
  return out
})

// ── Inspector: Zuständigkeit / Volle Sicht / Feld-Sichtbarkeit ─────────────────
const respText = computed(() => {
  const p = selectedPhase.value
  if (!p) return ''
  return responsibilityText(resolveResponsibility(p, {}), groupName)
})

interface FieldVis { key: string; label: string; tone: string; text: string; note: string }
const selectedFields = computed<FieldVis[]>(() => {
  const p = selectedPhase.value
  if (!p) return []
  return p.fields.map((ref_) => {
    const fd = fieldMap.value.get(ref_.ref) as FieldDef | undefined
    const vis = fd?.visibility
    let tone = 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300'
    let text = 'Alle Beteiligten'
    if (vis?.confidential) {
      tone = 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
      text = 'Vertraulich · nur ' + (vis.visibleToGroups.map(groupName).join(', ') || '—')
    } else if (vis && vis.visibleToGroups.length) {
      tone = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
      text = 'Gruppen: ' + vis.visibleToGroups.map(groupName).join(', ') + '  (+ Volle Sicht)'
    }
    const notes: string[] = []
    if (ref_.mode && ref_.mode !== 'editable') notes.push(ref_.mode === 'hidden' ? 'versteckt'
      : ref_.mode === 'readonly' ? 'nur lesen' : 'nur anhängen')
    if (ref_.visibleWhen) notes.push('bedingt sichtbar')
    return { key: ref_.ref, label: fd?.label || ref_.ref, tone, text, note: notes.join(' · ') }
  })
})

const rejectTargetLabel = computed(() => {
  const p = selectedPhase.value
  if (!p?.approval) return null
  const t = backToTarget(p.approval.onReject)
  if (!t) return 'Ablehnung (Auftrag endet)'
  const tp = phases.value.find((x) => x.key === t)
  return `Rücksprung zu „${tp?.label || t}"`
})

const meta = (kind: PhaseDef['kind']) => PHASE_KIND_META[kind]
</script>

<template>
  <div v-if="!phases.length" class="card-section text-sm text-gray-500 dark:text-gray-400">
    Noch keine Phasen – das Diagramm erscheint, sobald der Prozess Phasen hat.
  </div>

  <div v-else class="flex flex-col lg:flex-row gap-4">
    <!-- ── Diagramm ── -->
    <div class="flex-1 min-w-0 card-section">
      <div class="flex items-center justify-between gap-3 flex-wrap mb-3">
        <h3 class="section-title mb-0">Ablauf-Diagramm</h3>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500 dark:text-gray-400">
          <span v-for="k in EDGE_KINDS" :key="k" class="inline-flex items-center gap-1">
            <span class="inline-block w-4 h-0.5 rounded"
                  :style="{ backgroundColor: EDGE[k].stroke }"
                  :class="k === 'auto' ? 'opacity-70' : ''" />
            {{ EDGE[k].legend }}
          </span>
        </div>
      </div>

      <div ref="containerRef" class="relative px-10 py-2 overflow-x-auto">
        <!-- Pfeile -->
        <svg class="absolute left-0 top-0 pointer-events-none" :width="size.w" :height="size.h"
             :viewBox="`0 0 ${size.w} ${size.h}`">
          <defs>
            <marker v-for="k in EDGE_KINDS" :key="k" :id="`arw-${k}`" viewBox="0 0 6 6"
                    refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto"
                    markerUnits="userSpaceOnUse">
              <path d="M0,0 L6,3 L0,6 z" :fill="EDGE[k].stroke" />
            </marker>
          </defs>
          <path v-for="e in renderEdges" :key="e.key" :d="e.d" fill="none" :stroke="e.stroke"
                :stroke-width="e.strong ? 3 : 2" :stroke-dasharray="e.dash" :marker-end="e.marker" />
        </svg>

        <!-- Kanten-Beschriftungen -->
        <div v-for="e in renderEdges" :key="`l-${e.key}`"
             class="absolute z-10 pointer-events-none -translate-x-1/2 -translate-y-1/2
                    px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap
                    bg-white/90 dark:bg-[#1A2130]/90 border border-gray-200/70 dark:border-white/10"
             :style="{ left: `${e.lx}px`, top: `${e.ly}px`, color: e.stroke }">
          {{ e.label }}<span v-if="e.conditional" class="opacity-70"> · bedingt</span>
        </div>

        <!-- Knoten -->
        <div class="relative flex flex-col items-center gap-9 py-1">
          <button v-for="node in model.nodes" :key="node.id" type="button"
                  :ref="(el) => reg(node.id, el as any)" @click="select(node.index)"
                  class="w-full max-w-sm text-left rounded-2xl border bg-white dark:bg-[#212B3A]
                         shadow-sm px-4 py-3 transition hover:shadow-md"
                  :class="selected === node.index
                    ? 'border-[#3EAAB8] ring-2 ring-[#3EAAB8]/40'
                    : 'border-gray-200/80 dark:border-white/[0.09] hover:border-[#3EAAB8]/50'">
            <div class="flex items-center gap-2">
              <span class="inline-flex items-center justify-center w-7 h-7 rounded-lg text-sm shrink-0"
                    :class="meta(node.kind).badge">{{ meta(node.kind).icon }}</span>
              <div class="min-w-0 flex-1">
                <div class="font-semibold text-gray-900 dark:text-white truncate">{{ node.label }}</div>
                <div class="text-[11px] text-gray-500 dark:text-gray-400">
                  {{ PHASE_KIND_LABEL[node.kind] }} · <span class="font-mono">{{ node.id }}</span>
                </div>
              </div>
            </div>
            <div class="flex flex-wrap gap-1 mt-2">
              <span v-if="node.auto"
                    class="text-[10px] px-2 py-0.5 rounded-full bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                ⏭ {{ node.autoConditional ? 'automatisch (bedingt)' : 'automatisch' }}
              </span>
              <span v-if="node.departments.length"
                    class="text-[10px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
                👥 {{ node.departments.length }} Abteilung(en){{ node.departments.some(d => d.conditional) ? ' · tlw. bedingt' : '' }}
              </span>
              <span v-if="node.approval"
                    class="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                ✔ Freigabe
              </span>
            </div>
          </button>

          <!-- Terminals -->
          <div v-if="model.hasArchived" :ref="(el) => reg(TERMINAL_ARCHIVED, el as any)"
               class="px-4 py-2 rounded-full text-sm font-medium border
                      bg-gray-100 text-gray-600 border-gray-200
                      dark:bg-white/10 dark:text-gray-300 dark:border-white/10">
            ⏹ Archiviert
          </div>
          <div v-if="model.hasRejected" :ref="(el) => reg(TERMINAL_REJECTED, el as any)"
               class="px-4 py-2 rounded-full text-sm font-medium border
                      bg-red-50 text-red-700 border-red-200
                      dark:bg-red-900/20 dark:text-red-300 dark:border-red-500/30">
            ✗ Abgelehnt
          </div>
        </div>
      </div>
    </div>

    <!-- ── Detail / Sichtbarkeit ── -->
    <div class="lg:w-80 shrink-0">
      <div class="card-section lg:sticky lg:top-4">
        <template v-if="selectedPhase">
          <div class="flex items-center gap-2 mb-3">
            <span class="inline-flex items-center justify-center w-7 h-7 rounded-lg text-sm"
                  :class="meta(selectedPhase.kind).badge">{{ meta(selectedPhase.kind).icon }}</span>
            <div class="min-w-0">
              <div class="font-semibold text-gray-900 dark:text-white truncate">
                {{ selectedPhase.label || selectedPhase.key }}
              </div>
              <div class="text-[11px] text-gray-500 dark:text-gray-400">{{ PHASE_KIND_LABEL[selectedPhase.kind] }}</div>
            </div>
          </div>

          <!-- Zuständigkeit -->
          <div class="mb-3">
            <div class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Zuständig</div>
            <template v-if="selectedPhase.responsibility.kind === 'departments'">
              <ul class="space-y-1">
                <li v-for="d in selectedPhase.responsibility.rule" :key="d.group"
                    class="text-sm text-gray-800 dark:text-gray-100 flex items-start gap-1.5">
                  <span class="text-violet-500">👥</span>
                  <span>{{ groupName(d.group) }}
                    <span class="text-[11px] text-gray-400">
                      ({{ d.required ? 'erforderlich' : 'optional' }}<template v-if="d.when"> · bedingt</template>)
                    </span>
                  </span>
                </li>
              </ul>
            </template>
            <div v-else class="text-sm text-gray-800 dark:text-gray-100">{{ respText }}</div>
          </div>

          <!-- Volle Sicht -->
          <div class="mb-3">
            <div class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Sicht in dieser Phase</div>
            <div class="text-sm text-gray-800 dark:text-gray-100">
              <template v-if="selectedPhase.grantsFullView">
                Volle Sicht – Bearbeitende sehen <strong>alle nicht-vertraulichen</strong> Felder.
              </template>
              <template v-else>
                Normale Sicht – nur die unten genannten Freigaben greifen.
              </template>
            </div>
          </div>

          <!-- Approval-Details -->
          <div v-if="selectedPhase.approval" class="mb-3 rounded-xl bg-amber-50 dark:bg-amber-900/15
                      border border-amber-200/70 dark:border-amber-500/20 p-2.5">
            <div class="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-1">Freigabe</div>
            <div class="text-sm text-gray-800 dark:text-gray-100">{{ selectedPhase.approval.question }}</div>
            <div class="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
              Ja: „{{ selectedPhase.approval.approveLabel }}" · Nein: „{{ selectedPhase.approval.rejectLabel }}"<br>
              Bei Nein: {{ rejectTargetLabel }}<br>
              Mail-Link: {{ selectedPhase.approval.linkMode === 'public' ? 'öffentlich (mobil)' : 'intern (Firmennetz)' }}
            </div>
          </div>

          <!-- Feld-Sichtbarkeit -->
          <div class="mb-3">
            <div class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">
              Felder & Sichtbarkeit ({{ selectedFields.length }})
            </div>
            <ul v-if="selectedFields.length" class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
              <li v-for="f in selectedFields" :key="f.key" class="text-sm">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-gray-800 dark:text-gray-100 truncate">{{ f.label }}</span>
                  <span v-if="f.note" class="text-[10px] text-gray-400 shrink-0">{{ f.note }}</span>
                </div>
                <span class="inline-block mt-0.5 text-[10px] px-2 py-0.5 rounded-full" :class="f.tone">{{ f.text }}</span>
              </li>
            </ul>
            <div v-else class="text-sm text-gray-400">Keine Felder in dieser Phase.</div>
          </div>

          <button type="button" class="btn-secondary w-full text-sm"
                  @click="emit('select-phase', selected as number)">
            Im Editor bearbeiten
          </button>
        </template>
        <div v-else class="text-sm text-gray-500 dark:text-gray-400">
          Eine Phase im Diagramm anklicken, um Zuständigkeit und Sichtbarkeit zu sehen.
        </div>
      </div>
    </div>
  </div>
</template>
