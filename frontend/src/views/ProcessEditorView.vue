<script setup lang="ts">
/**
 * Visueller Prozess-Editor.
 *
 * Tabs: Ablauf (Phasenkette + Inspector), Feld-Katalog, Automationen (prozessweit),
 * Vorschau (reine Client-Simulation, kein Wegwerf-Ticket) und JSON (Rohform).
 * Gespeichert wird nur mit fehlerfreier Prüfung; veröffentlichte Versionen sind
 * schreibgeschützt.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { useProcessEditor } from '@/composables/useProcessEditor'
import type { FieldDef, PhaseDef, ProcessDefinition } from '@/types/process'
import { normalizeDefinition } from '@/lib/processNormalize'
import {
  SYSTEM_PROCESS_BLOCKED, SYSTEM_PROCESS_HINT, hasSystemReadonlyIssue, isSystemProcess,
} from '@/lib/processSystem'
import PhaseChain from '@/components/process/editor/PhaseChain.vue'
import PhaseInspector from '@/components/process/editor/PhaseInspector.vue'
import FieldCatalogPanel from '@/components/process/editor/FieldCatalogPanel.vue'
import AutomationList from '@/components/process/editor/AutomationList.vue'
import IssueList from '@/components/process/editor/IssueList.vue'
import CreatePermissionsEditor from '@/components/process/editor/CreatePermissionsEditor.vue'
import ProcessSimulator from '@/components/process/ProcessSimulator.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const ed = useProcessEditor()

const tab = ref<'flow' | 'fields' | 'rechte' | 'automations' | 'preview' | 'json'>('flow')
const selectedPhase = ref(0)
const jsonText = ref('')
const jsonError = ref<string | null>(null)

const key = computed(() => String(route.params.key || ''))
const version = computed(() => Number(route.params.version || 0))

const phaseErrorIndexes = computed(() => {
  const set = new Set<number>()
  for (const i of ed.issues.value) {
    if (i.severity !== 'error') continue
    const m = /^phases\.(\d+)/.exec(i.path)
    if (m) set.add(Number(m[1]))
  }
  return set
})

const currentPhase = computed<PhaseDef | null>(() => {
  const d = ed.draft.value
  if (!d || !d.phases.length) return null
  return d.phases[Math.min(selectedPhase.value, d.phases.length - 1)] ?? null
})

function setDefinition(part: Partial<ProcessDefinition>) {
  if (!ed.draft.value) return
  ed.update({ ...ed.draft.value, ...part })
}

function setPhase(next: PhaseDef) {
  const d = ed.draft.value
  if (!d) return
  const i = Math.min(selectedPhase.value, d.phases.length - 1)
  setDefinition({ phases: d.phases.map((p, j) => (j === i ? next : p)) })
}

function onFieldsChanged(fields: FieldDef[]) { setDefinition({ fields }) }
function onFieldRenamed(p: { from: string; to: string }) { ed.renameFieldKey(p.from, p.to) }

/**
 * System-Prozess: gehört zum Produkt und ist nicht änderbar. Der Server weist
 * jede Mutation mit 403 ab – hier wird trotzdem gesperrt und erklärt, damit man
 * nicht erst nach dem Speichern erfährt, dass die Arbeit umsonst war.
 */
const systemReadonly = computed(() => isSystemProcess(ed.meta.value))

async function save() {
  const ok = await ed.save()
  if (ok) showToast('Entwurf gespeichert')
  else if (ed.conflict.value) showToast('Konflikt: der Entwurf wurde zwischenzeitlich geändert', false)
  // Kann trotz gesperrter Knöpfe auftreten: das Merkmal fehlt bei einem älteren
  // Backend, die Ablehnung kommt dann erst als Antwort.
  else if (hasSystemReadonlyIssue(ed.serverIssues.value)) showToast(SYSTEM_PROCESS_BLOCKED, false)
  else showToast('Speichern fehlgeschlagen – bitte Fehlerliste prüfen', false)
}

async function publish() {
  if (!confirm('Diese Version veröffentlichen? Neue Aufträge verwenden ab sofort diesen Stand.')) return
  const ok = await ed.publish()
  if (!ok && hasSystemReadonlyIssue(ed.serverIssues.value)) {
    showToast(SYSTEM_PROCESS_BLOCKED, false)
    return
  }
  showToast(ok ? 'Version veröffentlicht' : 'Veröffentlichen fehlgeschlagen', ok)
}

function revert() {
  if (!confirm('Alle nicht gespeicherten Änderungen verwerfen?')) return
  ed.revert()
}

// ── JSON-Tab ────────────────────────────────────────────────────────────────
watch([tab, ed.draft], () => {
  if (tab.value === 'json' && ed.draft.value) {
    jsonText.value = JSON.stringify(ed.draft.value, null, 2)
    jsonError.value = null
  }
})

function applyJson() {
  try {
    const parsed = JSON.parse(jsonText.value)
    ed.update(normalizeDefinition(parsed))
    jsonError.value = null
    showToast('JSON übernommen')
  } catch (e: any) {
    jsonError.value = e?.message || 'Ungültiges JSON'
  }
}

// ── Verlassen-Schutz ────────────────────────────────────────────────────────
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (ed.dirty.value) { e.preventDefault(); e.returnValue = '' }
}
function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    if (ed.canSave.value) save()
  }
}

onBeforeRouteLeave(() => {
  if (ed.dirty.value && !confirm('Es gibt ungespeicherte Änderungen. Seite verlassen?')) return false
  return true
})

onMounted(async () => {
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', onKeydown)
  await ed.loadSources()
  await ed.load(key.value, version.value)
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <AppLayout>
    <div class="max-w-7xl mx-auto px-4 py-6">
      <!-- Kopf -->
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div class="min-w-0">
          <button @click="router.push('/settings?section=processes')"
                  class="text-xs text-gray-400 hover:text-[#3EAAB8] mb-1">← Prozesse</button>
          <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate">
            {{ ed.draft.value?.name || key }}
          </h1>
          <div class="text-xs text-gray-400 flex items-center gap-2 flex-wrap">
            <span class="font-mono">{{ key }}</span>
            <span>·</span>
            <span>Version {{ version }}</span>
            <span v-if="ed.meta.value" class="px-1.5 py-0.5 rounded-full text-[11px]"
                  :class="ed.meta.value.status === 'published'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                    : ed.meta.value.status === 'draft'
                      ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                      : 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400'">
              {{ ed.meta.value.status === 'published' ? 'Veröffentlicht'
                : ed.meta.value.status === 'draft' ? 'Entwurf' : 'Archiviert' }}
            </span>
            <span v-if="ed.dirty.value" class="text-amber-600 dark:text-amber-400">• ungespeichert</span>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <button v-if="ed.dirty.value" @click="revert" class="btn-secondary text-sm">Verwerfen</button>
          <button @click="save" :disabled="!ed.canSave.value || systemReadonly"
                  class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                         disabled:opacity-40 transition">
            {{ ed.saving.value ? 'Speichern…' : 'Speichern' }}
          </button>
          <button @click="publish" :disabled="!ed.canPublish.value || systemReadonly"
                  class="px-4 py-2 rounded-xl text-sm border border-[#3EAAB8] text-[#3EAAB8]
                         hover:bg-[#3EAAB8]/10 disabled:opacity-40 transition">
            Veröffentlichen
          </button>
        </div>
      </div>

      <!-- System-Prozess: steht VOR dem Unveränderlich-Hinweis, weil der Grund
           hier ein anderer ist (Produkt statt Version). -->
      <div v-if="systemReadonly && !ed.loading.value"
           class="rounded-xl border border-purple-200 dark:border-purple-500/30
                  bg-purple-50 dark:bg-purple-900/20 px-4 py-3 text-sm
                  text-purple-900 dark:text-purple-200 mb-4">
        <span class="font-medium">System-Prozess.</span> {{ SYSTEM_PROCESS_HINT }}
      </div>

      <div v-if="ed.readonly.value && !ed.loading.value"
           class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                  px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
        Diese Version ist {{ ed.meta.value?.status === 'published' ? 'veröffentlicht' : 'archiviert' }} und
        damit unveränderlich. Für Änderungen einen neuen Entwurf anlegen.
      </div>

      <div v-if="ed.conflict.value"
           class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                  px-4 py-3 text-sm text-red-800 dark:text-red-200 mb-4 flex items-center justify-between gap-3">
        <span>Der Entwurf wurde zwischenzeitlich an anderer Stelle geändert.</span>
        <button @click="ed.reloadFromServer()" class="btn-secondary text-xs py-1">Server-Stand laden</button>
      </div>

      <div v-if="ed.loadError.value" class="text-sm text-red-600">{{ ed.loadError.value }}</div>

      <div v-if="ed.loading.value" class="flex items-center justify-center py-20">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <template v-else-if="ed.draft.value">
        <IssueList :issues="ed.issues.value" class="mb-4" />

        <!-- Tabs -->
        <div class="flex gap-1 border-b border-gray-200 dark:border-white/10 mb-4 overflow-x-auto">
          <button v-for="t in ([
                    ['flow', 'Ablauf'], ['fields', 'Felder'], ['rechte', 'Rechte'], ['automations', 'Automationen'],
                    ['preview', 'Vorschau'], ['json', 'JSON'],
                  ] as const)" :key="t[0]"
                  @click="tab = t[0]"
                  class="px-4 py-2 text-sm border-b-2 -mb-px whitespace-nowrap transition"
                  :class="tab === t[0]
                    ? 'border-[#3EAAB8] text-[#3EAAB8]'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'">
            {{ t[1] }}
          </button>
        </div>

        <!-- Kopfdaten -->
        <section v-if="tab === 'flow' || tab === 'fields'" id="pe-top" class="card-section mb-4">
          <div class="grid md:grid-cols-3 gap-3">
            <div class="md:col-span-2">
              <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Name</label>
              <input :value="ed.draft.value.name" :disabled="ed.readonly.value" class="afi w-full"
                     @input="setDefinition({ name: ($event.target as HTMLInputElement).value })" />
            </div>
            <div>
              <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Symbol</label>
              <input :value="ed.draft.value.icon ?? ''" :disabled="ed.readonly.value" class="afi w-full"
                     placeholder="z. B. 📝" maxlength="4"
                     @input="setDefinition({ icon: ($event.target as HTMLInputElement).value || null })" />
            </div>
            <div class="md:col-span-3">
              <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Beschreibung</label>
              <textarea :value="ed.draft.value.description ?? ''" :disabled="ed.readonly.value"
                        rows="2" class="afi w-full"
                        @input="setDefinition({ description: ($event.target as HTMLTextAreaElement).value || null })" />
            </div>
          </div>
        </section>

        <!-- Ablauf -->
        <div v-if="tab === 'flow'" class="grid lg:grid-cols-[280px_1fr] gap-4 items-start">
          <div class="card-section lg:sticky lg:top-4">
            <PhaseChain :model-value="ed.draft.value.phases" :selected="selectedPhase"
                        :readonly="ed.readonly.value" :error-phases="phaseErrorIndexes"
                        @update:model-value="setDefinition({ phases: $event })"
                        @select="selectedPhase = $event" />
          </div>
          <div>
            <fieldset :disabled="ed.readonly.value" class="contents">
              <PhaseInspector v-if="currentPhase" :model-value="currentPhase" :index="selectedPhase"
                              :catalog="ed.draft.value.fields" :groups="ed.sources.groups"
                              :users="ed.sources.users" :field-keys="ed.fieldKeys.value"
                              :field-labels="ed.fieldLabels.value" :taken-ids="ed.automationIds.value"
                              :readonly="ed.readonly.value"
                              @update:model-value="setPhase" />
              <p v-else class="text-sm text-gray-400 italic">Keine Phase ausgewählt.</p>
            </fieldset>
          </div>
        </div>

        <!-- Felder -->
        <div v-else-if="tab === 'fields'">
          <!-- fieldset deaktiviert nativ ALLE Bedienelemente darin – so kann kein
               Unter-Editor den Schreibschutz vergessen. -->
          <fieldset :disabled="ed.readonly.value" class="contents">
            <FieldCatalogPanel :model-value="ed.draft.value.fields" :groups="ed.sources.groups"
                               @update:model-value="onFieldsChanged" @renamed="onFieldRenamed" />
          </fieldset>
        </div>

        <!-- Erstellrechte -->
        <div v-else-if="tab === 'rechte'">
          <fieldset :disabled="ed.readonly.value" class="contents">
            <CreatePermissionsEditor :model-value="ed.draft.value.createPermissions"
                                     :groups="ed.sources.groups" :users="ed.sources.users"
                                     @update:model-value="setDefinition({ createPermissions: $event })" />
          </fieldset>
        </div>

        <!-- Prozessweite Automationen -->
        <div v-else-if="tab === 'automations'" class="card-section">
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
            Diese Automationen gelten in <b>jeder</b> Phase des Prozesses – z. B. eine
            Erinnerung, die überall greift.
          </p>
          <fieldset :disabled="ed.readonly.value" class="contents">
            <AutomationList :model-value="ed.draft.value.automations" :field-keys="ed.fieldKeys.value"
                            :field-labels="ed.fieldLabels.value" :groups="ed.sources.groups"
                            title="Prozessweite Automationen" :taken-ids="ed.automationIds.value"
                            @update:model-value="setDefinition({ automations: $event })" />
          </fieldset>
        </div>

        <!-- Vorschau -->
        <div v-else-if="tab === 'preview'">
          <ProcessSimulator :definition="ed.draft.value" :sources="ed.sources" />
        </div>

        <!-- JSON -->
        <div v-else class="card-section">
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">
            Rohform der Definition. Änderungen werden erst mit „JSON übernehmen" wirksam.
          </p>
          <textarea v-model="jsonText" rows="24" spellcheck="false"
                    class="afi w-full font-mono text-xs" :disabled="ed.readonly.value" />
          <p v-if="jsonError" class="text-sm text-red-600 mt-2">{{ jsonError }}</p>
          <div class="flex justify-end mt-2">
            <button @click="applyJson" :disabled="ed.readonly.value" class="btn-secondary text-sm">
              JSON übernehmen
            </button>
          </div>
        </div>
      </template>
    </div>
  </AppLayout>
</template>
