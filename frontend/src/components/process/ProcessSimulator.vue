<script setup lang="ts">
/**
 * Vorschau eines Prozess-Entwurfs – reine CLIENT-Simulation.
 *
 * Es wird KEIN Ticket angelegt und keine Mail versendet; die Logik spiegelt die
 * Server-Regeln (processSim). Zum Prüfen, wie das Formular aussieht, welche
 * Felder wann erscheinen und wer was sieht.
 */
import { computed, ref, watch } from 'vue'
import type { OptionSources, ProcessDefinition } from '@/types/process'
import type { ApprovalAct, SimFieldError, SimState, SimViewer } from '@/lib/processSim'
import {
  currentApproval, currentPhase, isTerminal, resolveResponsibility, responsibilityText,
  simAdvance, simDecide, simJumpTo, simReject, simSetValues, startSim,
} from '@/lib/processSim'
import { STATUS_LABEL } from '@/lib/processSchema'
import SchemaForm from '@/components/process/form/SchemaForm.vue'
import SchemaReadonlyView from '@/components/process/form/SchemaReadonlyView.vue'

const props = defineProps<{
  definition: ProcessDefinition
  sources?: OptionSources
}>()

const state = ref<SimState>(startSim(props.definition))
const errors = ref<SimFieldError[]>([])

/** Rolle, aus deren Sicht die Vorschau gerendert wird. */
const roleKey = ref<string>('admin')

const roles = computed(() => [
  { key: 'admin', label: 'Admin (sieht alles)' },
  { key: 'full', label: 'Vollsicht (z. B. Ersteller:in)' },
  ...(props.sources?.groups ?? []).map((g) => ({ key: `group:${g.id}`, label: `Mitglied „${g.name}"` })),
  { key: 'none', label: 'Beteiligt ohne Vollsicht' },
])

const viewer = computed<SimViewer>(() => {
  if (roleKey.value === 'admin') return { fullView: true, isAdmin: true, groupIds: [] }
  if (roleKey.value === 'full') return { fullView: true, isAdmin: false, groupIds: [] }
  if (roleKey.value.startsWith('group:')) {
    return { fullView: false, isAdmin: false, groupIds: [roleKey.value.slice(6)] }
  }
  return { fullView: false, isAdmin: false, groupIds: [] }
})

const phase = computed(() => currentPhase(props.definition, state.value.runtime))
const done = computed(() => isTerminal(props.definition, state.value.runtime))
const responsibility = computed(() =>
  phase.value ? resolveResponsibility(phase.value, state.value.values) : null)
const approval = computed(() => currentApproval(props.definition, state.value))
const reason = ref('')
/** NUR Vorschau: Pflichtfelder beim Weiterschalten ignorieren (Durchklicken). */
const bypass = ref(false)
const phaseIndexNow = computed(() => state.value.runtime.current_index)

/** Niemand zuständig – im echten Betrieb bliebe der Auftrag liegen. */
const offeneZustaendigkeit = computed(() => {
  const r = responsibility.value
  if (!r) return false
  if (r.kind === 'departments') return !r.departments?.length
  if (r.kind === 'group') return !r.group
  if (r.kind === 'user') return !r.user
  return false
})

function decide(act: ApprovalAct) {
  const res = simDecide(props.definition, state.value, act,
                        { reason: reason.value, bypassRequired: bypass.value })
  errors.value = res.errors
  if (!res.errors.length) {
    state.value = res.state
    reason.value = ''
  }
}

/** NUR Vorschau: frei zu einer beliebigen Phase springen. */
function jumpTo(idx: number) {
  state.value = simJumpTo(props.definition, state.value, idx)
  errors.value = []
  reason.value = ''
}

const groupName = (id: string) =>
  props.sources?.groups.find((g) => g.id === id)?.name || id

// Definition ändert sich im Editor → Simulation neu starten
watch(() => props.definition, () => reset(), { deep: true })

function reset() {
  state.value = startSim(props.definition)
  errors.value = []
  reason.value = ''
}

function onValues(v: Record<string, unknown>) {
  state.value = simSetValues(props.definition, state.value, v)
  errors.value = []
}

function advance() {
  const res = simAdvance(props.definition, state.value, undefined, { bypassRequired: bypass.value })
  errors.value = res.errors
  if (!res.errors.length) state.value = res.state
}

function reject() { state.value = simReject(state.value) }
</script>

<template>
  <div class="space-y-4">
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 flex items-start justify-between gap-3">
      <span>
        Vorschau ohne echtes Ticket: nichts wird gespeichert, keine Mail versendet.
        Die Regeln entsprechen dem Server – der Server bleibt aber maßgeblich.
      </span>
      <button @click="reset" class="btn-secondary text-xs py-1 shrink-0">Zurücksetzen</button>
    </div>

    <div class="grid lg:grid-cols-[1fr_320px] gap-4 items-start">
      <div class="space-y-4">
        <!-- Statuszeile -->
        <div class="card-section flex items-center gap-3 flex-wrap">
          <div>
            <div class="text-xs text-gray-400">Aktuelle Phase</div>
            <div class="text-sm font-medium text-gray-800 dark:text-gray-100">
              {{ done ? '— abgeschlossen —' : (phase?.label || phase?.key || '—') }}
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-400">Status</div>
            <div class="text-sm text-gray-700 dark:text-gray-200">
              {{ STATUS_LABEL[state.status] || state.status }}
            </div>
          </div>
          <div v-if="responsibility">
            <div class="text-xs text-gray-400">Zuständig</div>
            <div class="text-sm"
                 :class="offeneZustaendigkeit ? 'text-red-500' : 'text-gray-700 dark:text-gray-200'">
              {{ responsibilityText(responsibility, groupName) }}
            </div>
          </div>
          <div class="ml-auto">
            <label class="block text-xs text-gray-400 mb-1">Phase (Vorschau)</label>
            <select :value="phaseIndexNow" class="afi text-sm"
                    @change="jumpTo(Number(($event.target as HTMLSelectElement).value))">
              <option v-for="(p, i) in definition.phases" :key="p.key" :value="i">
                {{ i + 1 }}. {{ p.label || p.key }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-gray-400 mb-1">Ansicht als</label>
            <select v-model="roleKey" class="afi text-sm">
              <option v-for="r in roles" :key="r.key" :value="r.key">{{ r.label }}</option>
            </select>
          </div>
        </div>

        <!-- Formular der aktuellen Phase -->
        <div v-if="!done && phase">
          <SchemaForm :definition="definition" :phase="phase" :model-value="state.values"
                      :viewer="viewer" :errors="errors" :sources="sources"
                      @update:model-value="onValues" />

          <div v-if="errors.length"
               class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-200 mt-3">
            <div class="font-medium mb-1">Phase kann nicht abgeschlossen werden:</div>
            <ul class="list-disc list-inside">
              <li v-for="(e, i) in errors" :key="i">
                <span class="font-mono text-xs opacity-70">{{ e.path }}</span> — {{ e.message }}
              </li>
            </ul>
          </div>

          <!-- NUR Vorschau: ohne Pflichtangaben in die nächste Phase schauen. -->
          <label class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400
                        mt-3 cursor-pointer select-none w-fit">
            <input type="checkbox" v-model="bypass"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                          focus:ring-[#3EAAB8]/30 cursor-pointer" />
            <span>Pflichtfelder in der Vorschau ignorieren (zum Durchklicken)</span>
          </label>

          <!-- Freigabe-Phase: die Frage aus der Definition, zwei Antworten -->
          <div v-if="approval" class="card-section mt-3 space-y-3">
            <p class="text-sm font-medium text-gray-800 dark:text-gray-100">{{ approval.question }}</p>
            <p class="text-xs text-gray-400">
              Im Betrieb entscheidet die zuständige Stelle
              {{ approval.externalLink ? 'in der App oder per Mail-Link' : 'nur in der App' }}.
            </p>
            <div>
              <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                Begründung
                <span v-if="approval.requireReason">(bei „{{ approval.rejectLabel }}" Pflicht)</span>
              </label>
              <textarea v-model="reason" rows="2" class="afi w-full resize-none"
                        placeholder="Nur nötig, wenn abgelehnt wird" />
            </div>
            <div class="flex items-center gap-2">
              <button @click="decide('approve')"
                      class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7] transition">
                {{ approval.approveLabel }}
              </button>
              <button @click="decide('reject')" class="btn-secondary text-sm">
                {{ approval.rejectLabel }}
              </button>
            </div>
          </div>

          <div v-else class="flex items-center gap-2 mt-3">
            <button @click="advance"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7] transition">
              Phase abschließen
            </button>
            <button @click="reject" class="btn-secondary text-sm">Ablehnen</button>
          </div>
        </div>

        <div v-else class="card-section text-center py-8">
          <div class="text-sm text-gray-500 dark:text-gray-400">
            {{ state.status === 'rejected' ? 'Auftrag abgelehnt.' : 'Prozess durchlaufen – Auftrag archiviert.' }}
          </div>
          <button @click="reset" class="btn-secondary text-sm mt-3">Erneut simulieren</button>
        </div>

        <!-- Gesammelte Werte aus Sicht der gewählten Rolle -->
        <div class="card-section">
          <h3 class="section-title">Erfasste Daten (Sicht: {{ roles.find(r => r.key === roleKey)?.label }})</h3>
          <SchemaReadonlyView :definition="definition" :values="state.values" :viewer="viewer"
                              :sources="sources" />
        </div>
      </div>

      <!-- Verlauf -->
      <div class="card-section lg:sticky lg:top-4">
        <h3 class="section-title">Verlauf</h3>
        <ol class="space-y-2">
          <li v-for="(e, i) in state.events" :key="i" class="text-xs text-gray-600 dark:text-gray-300">
            <span class="inline-block w-1.5 h-1.5 rounded-full bg-[#3EAAB8] mr-1.5 align-middle" />
            {{ e.text }}
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>
