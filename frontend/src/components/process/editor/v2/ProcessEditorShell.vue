<script setup lang="ts">
/**
 * Neuer Prozess-Editor (v2) – Shell / Grundgerüst (M0).
 *
 * Ersetzt die vier Reiter durch ein linkes Navigationsraster (Prozess-Bereiche
 * oben, Phasenliste darunter) und einen Arbeitsbereich rechts – so ist immer
 * sichtbar, wo man ist, ohne lange Scroll-Strecken. Der Zustandskern
 * (useProcessEditor) und ALLE bestehenden Unter-Editoren werden unverändert
 * weiterverwendet; nur die Anordnung ist neu. Weitere Ausbaustufen (Phasen-
 * Pipeline, Inspector, Drawer, Registry) setzen darauf auf.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { useProcessEditor } from '@/composables/useProcessEditor'
import { useProcessEditorFlag } from '@/composables/useProcessEditorFlag'
import type { PhaseDef, ProcessDefinition } from '@/types/process'
import { normalizeDefinition } from '@/lib/processNormalize'
import {
  SYSTEM_PROCESS_BLOCKED, SYSTEM_PROCESS_HINT, hasSystemReadonlyIssue, isSystemProcess,
} from '@/lib/processSystem'
import PhaseChain from '@/components/process/editor/PhaseChain.vue'
import PhaseInspector from '@/components/process/editor/PhaseInspector.vue'
import FormBuilder from '@/components/process/editor/FormBuilder.vue'
import AutomationList from '@/components/process/editor/AutomationList.vue'
import IssueList from '@/components/process/editor/IssueList.vue'
import CreatePermissionsEditor from '@/components/process/editor/CreatePermissionsEditor.vue'
import ProcessSimulator from '@/components/process/ProcessSimulator.vue'

type Section = 'stammdaten' | 'permissions' | 'automations' | 'phase' | 'preview' | 'json'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const ed = useProcessEditor()
const editorFlag = useProcessEditorFlag()

const section = ref<Section>('phase')
const selectedPhase = ref(0)

const PH_FELD = '{{feld.key}}'
const PH_ERSTELLT = '{{erstellt}}'
const TITEL_PLATZHALTER = 'z. B. Onboarding Mitarbeiter:innen – {{base.first_name}} {{base.last_name}}'
const jsonText = ref('')
const jsonError = ref<string | null>(null)

const key = computed(() => String(route.params.key || ''))
const version = computed(() => Number(route.params.version || 0))

function switchToLegacy() {
  if (ed.dirty.value
      && !confirm('Zum klassischen Editor wechseln? Nicht gespeicherte Änderungen gehen verloren.')) return
  editorFlag.set(false)
}

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

const statusLabel = computed(() => {
  const s = ed.meta.value?.status
  return s === 'published' ? 'Veröffentlicht' : s === 'draft' ? 'Entwurf' : 'Archiviert'
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

function selectPhase(i: number) {
  selectedPhase.value = i
  section.value = 'phase'
}

function onFieldRenamed(p: { from: string; to: string }) { ed.renameFieldKey(p.from, p.to) }

const systemReadonly = computed(() => isSystemProcess(ed.meta.value))

async function save() {
  const ok = await ed.save()
  if (ok) showToast('Entwurf gespeichert')
  else if (ed.conflict.value) showToast('Konflikt: der Entwurf wurde zwischenzeitlich geändert', false)
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

// ── JSON ──────────────────────────────────────────────────────────────────
watch([section, ed.draft], () => {
  if (section.value === 'json' && ed.draft.value) {
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

// Ein Navigationseintrag im linken Raster.
const railBtn = (active: boolean) =>
  active
    ? 'bg-[#3EAAB8]/12 text-[#3EAAB8] font-medium'
    : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'
const RAIL_BASE = 'w-full text-left px-3 py-2 rounded-lg text-sm transition'
const RAIL_LABEL = 'text-[11px] font-semibold uppercase tracking-wider text-gray-400 px-3 pt-1 pb-1.5'
</script>

<template>
  <AppLayout>
    <div class="max-w-[1400px] mx-auto px-4 py-6">
      <!-- Kopf -->
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div class="min-w-0">
          <button @click="router.push('/settings?section=processes')"
                  class="text-xs text-gray-400 hover:text-[#3EAAB8] mb-1">← Prozesse</button>
          <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate flex items-center gap-2">
            <span v-if="ed.draft.value?.icon">{{ ed.draft.value.icon }}</span>
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
              {{ statusLabel }}
            </span>
            <span v-if="ed.dirty.value" class="text-amber-600 dark:text-amber-400">• ungespeichert</span>
            <span v-if="ed.errors.value" class="text-red-600 dark:text-red-400">
              · {{ ed.errors.value }} Fehler
            </span>
            <span v-else-if="ed.warnings.value" class="text-amber-600 dark:text-amber-400">
              · {{ ed.warnings.value }} Hinweise
            </span>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <button type="button" @click="switchToLegacy"
                  class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/15
                         text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5 transition"
                  title="Zur klassischen Ansicht wechseln">
            Klassischer Editor
          </button>
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

      <!-- Hinweisbänder -->
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
        <div class="grid lg:grid-cols-[240px_1fr] gap-5 items-start">
          <!-- Linkes Navigationsraster -->
          <aside class="lg:sticky lg:top-4 space-y-3">
            <nav class="card-section !p-2 space-y-0.5">
              <p :class="RAIL_LABEL">Prozess</p>
              <button type="button" @click="section = 'stammdaten'"
                      :class="[RAIL_BASE, railBtn(section === 'stammdaten')]">Stammdaten</button>
              <button type="button" @click="section = 'permissions'"
                      :class="[RAIL_BASE, railBtn(section === 'permissions')]">Erstellrechte</button>
              <button type="button" @click="section = 'automations'"
                      :class="[RAIL_BASE, railBtn(section === 'automations')]">Prozessweite Automationen</button>
            </nav>

            <div class="card-section !p-3">
              <p :class="RAIL_LABEL" class="!px-1">Phasen</p>
              <PhaseChain :model-value="ed.draft.value.phases"
                          :selected="section === 'phase' ? selectedPhase : -1"
                          :readonly="ed.readonly.value" :error-phases="phaseErrorIndexes"
                          @update:model-value="setDefinition({ phases: $event })"
                          @select="selectPhase" />
            </div>

            <nav class="card-section !p-2 space-y-0.5">
              <button type="button" @click="section = 'preview'"
                      :class="[RAIL_BASE, railBtn(section === 'preview')]">Vorschau</button>
              <button type="button" @click="section = 'json'"
                      :class="[RAIL_BASE, railBtn(section === 'json')]">JSON</button>
            </nav>
          </aside>

          <!-- Arbeitsbereich -->
          <div class="min-w-0 space-y-4">
            <IssueList :issues="ed.issues.value" />

            <fieldset :disabled="ed.readonly.value" class="contents">
              <!-- Stammdaten -->
              <section v-if="section === 'stammdaten'" class="card-section">
                <h2 class="section-title">Stammdaten</h2>
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
                  <div class="md:col-span-3">
                    <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300
                                  cursor-pointer select-none w-fit">
                      <input type="checkbox" :checked="ed.draft.value.titleEditable"
                             :disabled="ed.readonly.value"
                             class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                                    focus:ring-[#3EAAB8]/30 cursor-pointer"
                             @change="setDefinition({ titleEditable: ($event.target as HTMLInputElement).checked })" />
                      <span>Titel darf nach dem Anlegen geändert werden</span>
                    </label>
                    <p class="text-xs text-gray-400 mt-1">
                      Abgewählt wird der Auftrags-Titel beim Anlegen festgelegt und ist danach überall nur
                      lesbar – das setzt der Server durch, nicht nur die Oberfläche.
                    </p>
                  </div>
                  <div class="md:col-span-3">
                    <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel-Vorlage (optional)</label>
                    <input :value="ed.draft.value.titleTemplate ?? ''" :disabled="ed.readonly.value"
                           class="afi w-full" maxlength="255" :placeholder="TITEL_PLATZHALTER"
                           @input="setDefinition({ titleTemplate: ($event.target as HTMLInputElement).value || null })" />
                    <p class="text-xs text-gray-400 mt-1">
                      Gesetzt, wird der Titel beim Anlegen automatisch erzeugt. Platzhalter:
                      <span class="font-mono">{{ PH_FELD }}</span> (Werte der Startphase) und
                      <span class="font-mono">{{ PH_ERSTELLT }}</span> (Erstellzeitpunkt).
                    </p>
                  </div>
                </div>
              </section>

              <!-- Erstellrechte -->
              <section v-else-if="section === 'permissions'" class="card-section">
                <h2 class="section-title">Wer darf diesen Prozess starten?</h2>
                <CreatePermissionsEditor :model-value="ed.draft.value.createPermissions"
                                         :groups="ed.sources.groups" :users="ed.sources.users"
                                         @update:model-value="setDefinition({ createPermissions: $event })" />
              </section>

              <!-- Prozessweite Automationen -->
              <section v-else-if="section === 'automations'" class="card-section">
                <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
                  Diese Automationen gelten in <b>jeder</b> Phase des Prozesses – z. B. eine Erinnerung,
                  die überall greift.
                </p>
                <AutomationList :model-value="ed.draft.value.automations" :field-keys="ed.fieldKeys.value"
                                :field-labels="ed.fieldLabels.value" :field-widgets="ed.fieldWidgets.value"
                                :groups="ed.sources.groups" :process-name="ed.draft.value.name"
                                title="Prozessweite Automationen" :taken-ids="ed.automationIds.value"
                                @update:model-value="setDefinition({ automations: $event })" />
              </section>

              <!-- Phase (Formular + Einstellungen) -->
              <template v-else-if="section === 'phase'">
                <template v-if="currentPhase">
                  <FormBuilder :definition="ed.draft.value" :phase-index="selectedPhase"
                               :groups="ed.sources.groups" :field-keys="ed.fieldKeys.value"
                               :field-labels="ed.fieldLabels.value" :readonly="ed.readonly.value"
                               @update:definition="ed.update" @renamed="onFieldRenamed" />
                  <PhaseInspector :model-value="currentPhase" :index="selectedPhase"
                                  :catalog="ed.draft.value.fields" :groups="ed.sources.groups"
                                  :users="ed.sources.users" :field-keys="ed.fieldKeys.value"
                                  :field-labels="ed.fieldLabels.value" :field-widgets="ed.fieldWidgets.value"
                                  :taken-ids="ed.automationIds.value" :phases="ed.draft.value.phases"
                                  :process-key="ed.draft.value.key" :process-name="ed.draft.value.name"
                                  :readonly="ed.readonly.value"
                                  @update:model-value="setPhase" />
                </template>
                <p v-else class="text-sm text-gray-400 italic card-section">
                  Noch keine Phase vorhanden – links unter „Phasen" eine anlegen.
                </p>
              </template>

              <!-- Vorschau -->
              <div v-else-if="section === 'preview'">
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
            </fieldset>
          </div>
        </div>
      </template>
    </div>
  </AppLayout>
</template>
