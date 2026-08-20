<script setup lang="ts">
/**
 * Auftrag aus einem veröffentlichten Prozess anlegen.
 * Das Formular wird vollständig aus der Prozess-Definition gerendert.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition } from '@/types/process'
import type { SimFieldError, SimViewer } from '@/lib/processSim'
import { validatePhaseCompletion, validateValues } from '@/lib/processSim'
import { normalizeDefinition } from '@/lib/processNormalize'
import { errorCode, errorMessage, issuesFromError } from '@/lib/processErrors'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { applyComputed } from '@/lib/conditionDsl'
import * as processesApi from '@/api/processes'
import { createTicket, advanceTicket } from '@/api/processTickets'
import { uploadAttachment } from '@/api/processAttachments'
import { useAuthStore } from '@/stores/authStore'
import SchemaForm from '@/components/process/form/SchemaForm.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const loading = ref(true)
const submitting = ref(false)
const selectedKey = ref<string>(String(route.params.key || ''))
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const title = ref('')
/**
 * Priorität wird NICHT abgefragt: die Anzeige ist überall ausgeblendet, bis
 * geklärt ist, wie sie sinnvoll genutzt wird. Feld und API bleiben – deshalb
 * geht weiter der Standardwert mit, statt ihn aus dem Aufruf zu entfernen.
 */
const priority = ref('normal')
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>(emptySources())
/** Beim Anlegen gewählte, noch nicht hochgeladene Dateien je Anhang-Feld. */
const pendingAttachments = ref<Record<string, File[]>>({})

/**
 * Welche Felder die erstellende Person sehen und ausfüllen darf, sagt der Server
 * (GET /processes/{key}/field-access). Selbst herleiten kann das Frontend es
 * nicht – es kennt die Gruppen-Mitgliedschaft nicht. Ohne die Auskunft bekäme
 * z. B. beim Onboarding jemand Eingabefelder für vertrauliche Angaben zu sehen,
 * die der Server anschließend verwirft.
 */
const zugriff = ref<{ visible: Set<string>; editable: Set<string> } | null>(null)
/** Der Prozess existiert (noch) nicht als VERÖFFENTLICHTE Version. */
const nichtVeroeffentlicht = ref(false)
const viewer = computed<SimViewer>(() => ({
  fullView: false,
  isAdmin: false,
  groupIds: [],
  visibleKeys: zugriff.value?.visible ?? new Set<string>(),
  editableKeys: zugriff.value?.editable ?? new Set<string>(),
}))

const startPhase = computed(() => definition.value?.phases?.[0] ?? null)
/** Prozess global deaktiviert? Dann kein Formular, sondern ein Hinweis. */
const deaktiviert = ref(false)

async function loadProcess(key: string) {
  if (!key) { definition.value = null; return }
  deaktiviert.value = false
  try {
    const [row, access] = await Promise.all([
      processesApi.getPublished(key),
      processesApi.getFieldAccess(key),
    ])
    deaktiviert.value = row.disabled === true
    definition.value = normalizeDefinition(row.definition)
    zugriff.value = {
      visible: new Set(access.visible_fields),
      editable: new Set(access.editable_fields),
    }
    title.value = row.name
    values.value = {}
    pendingAttachments.value = {}
    errors.value = []
  } catch (e) {
    definition.value = null
    zugriff.value = null
    // Den Grund festhalten: „nicht veröffentlicht" ist der häufigste Fall (die
    // Definitionen sind noch nicht eingespielt) und braucht einen anderen
    // Hinweis als ein echter Fehler.
    nichtVeroeffentlicht.value = errorCode(e) === 'PROCESS_NOT_FOUND'
    if (!nichtVeroeffentlicht.value) {
      showToast(errorMessage(e, 'Prozess konnte nicht geladen werden'), false)
    }
  }
}

/** Abgeleitete Felder wie auf dem Server nachziehen (sonst blieben sie leer und
 *  ein berechnetes Pflichtfeld wäre nie erfüllbar). */
function onValues(next: Record<string, unknown>) {
  values.value = definition.value ? applyComputed(definition.value.fields, next) : next
}

/** Fehler ohne Feldbezug (Phasen-Regeln, Server-Meldungen) – die zeigt das
 *  Formular selbst nicht an, sie brauchen eine eigene Liste. */
const generalErrors = computed(() => {
  const fieldKeys = new Set(definition.value?.fields.map((f) => f.key) ?? [])
  return errors.value.filter((e) => !fieldKeys.has(e.path))
})

async function submit() {
  if (!definition.value || !startPhase.value) return
  // Client-Vorprüfung (der Server prüft erneut und ist maßgeblich)
  const shapeErrors = validateValues(definition.value, values.value)
  const requiredErrors = validatePhaseCompletion(definition.value, startPhase.value, values.value)
  errors.value = [...shapeErrors, ...requiredErrors]
  if (errors.value.length) {
    showToast('Bitte die markierten Felder prüfen', false)
    return
  }
  submitting.value = true
  try {
    // Anhänge einsammeln (je Feld können mehrere Dateien gewählt sein).
    const files: { fieldKey: string; file: File }[] = []
    for (const [fieldKey, fs] of Object.entries(pendingAttachments.value)) {
      for (const file of fs) files.push({ fieldKey, file })
    }
    const hasFiles = files.length > 0

    // 1) Anlegen. Mit Anhängen NICHT sofort weiterschalten (autoStart=false) –
    //    erst hochladen, dann selbst :advance, damit die Freigabe-Mail die
    //    Anhänge mitbekommt. Schlägt schon das Anlegen fehl, existiert kein
    //    Ticket → auf dem Formular bleiben und Feldfehler zeigen.
    let ticket
    try {
      ticket = await createTicket({
        processKey: definition.value.key,
        title: title.value || null,
        priority: priority.value,
        values: values.value,
        autoStart: !hasFiles,
      })
    } catch (e) {
      const issues = issuesFromError(e)
      errors.value = issues.map((i) => ({ path: i.path, code: i.code, message: i.message }))
      showToast(errorMessage(e, 'Anlegen fehlgeschlagen'), false)
      return
    }

    // 2) Ab hier EXISTIERT das Ticket (parkt in der Startphase). Ein Fehler beim
    //    Hochladen/Weitergeben darf NICHT zu einem zweiten Anlege-Versuch (und
    //    damit Duplikat) führen: stattdessen in den Auftrag springen, wo man
    //    Dateien nachreichen und selbst weitergeben kann.
    if (hasFiles) {
      try {
        for (const { fieldKey, file } of files) {
          await uploadAttachment(ticket.id, file, { fieldKey })
        }
        await advanceTicket(ticket.id)
      } catch (e) {
        showToast(`Auftrag #${ticket.id} wurde angelegt, aber Hochladen/Weitergeben `
                  + `schlug fehl (${errorMessage(e, 'Fehler')}). Bitte im Auftrag prüfen `
                  + `und weitergeben.`, false)
        router.push(`/prozess-auftraege/${ticket.id}?ansicht=bearbeiten`)
        return
      }
    }
    showToast('Auftrag angelegt')
    // Nach dem Anlegen zur Übersicht (einheitlich mit dem Basis-Ticket).
    router.push('/dashboard')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  // auth.isAdmin: normale Nutzer:innen direkt über den öffentlichen
  // /groups-Endpunkt (der Admin-Endpunkt gäbe 403 → rohe IDs statt Namen).
  sources.value = await loadOptionSources(auth.isAdmin)
  if (selectedKey.value) await loadProcess(selectedKey.value)
  loading.value = false
})
</script>

<template>
  <AppLayout>
    <div class="max-w-4xl mx-auto px-4 py-6">
      <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 mb-4">Neuer Auftrag</h1>

      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <template v-else>
        <!-- Kein Prozess-Auswahlfeld: der Einstieg ist der Katalog
             (/prozess-auftraege/neu). Ein zweites Auswahlfeld hier hätte den
             Prozess gewechselt, ohne die Adresse zu ändern – ein Neuladen wäre
             dann beim alten gelandet. -->
        <div v-if="!definition"
             class="rounded-2xl border border-amber-200 dark:border-amber-500/30
                    bg-amber-50 dark:bg-amber-900/20 px-5 py-4">
          <p class="text-sm text-amber-900 dark:text-amber-200">
            <template v-if="nichtVeroeffentlicht">
              Für <span class="font-mono">{{ selectedKey }}</span> ist keine
              veröffentlichte Version vorhanden – deshalb lässt sich dazu kein
              Auftrag anlegen.
            </template>
            <template v-else>
              Dieser Prozess konnte nicht geladen werden.
            </template>
          </p>
          <!-- Für Admins der konkrete nächste Schritt: die Definitionen liegen im
               Paket (backend/seeds/processes/), müssen aber je Installation
               eingespielt werden. Ohne diesen Hinweis sucht man den Fehler in der
               Oberfläche, obwohl nur die Datenbank leer ist. Eingespielt wird in
               den Einstellungen – ein Server-Zugang ist dafür nicht nötig. -->
          <p v-if="nichtVeroeffentlicht && auth.isAdmin"
             class="text-xs text-amber-800 dark:text-amber-300/90 mt-2">
            Die mitgelieferten Prozess-Definitionen sind noch nicht eingespielt. Das geht in den
            Einstellungen unter „Prozesse“ mit „Mitgelieferte Prozesse einspielen“: erst ein
            Trockenlauf, der nichts schreibt, dann das Einspielen nach Bestätigung. Vorhandene
            Prozesse werden dabei übersprungen.
          </p>
          <div class="flex items-center gap-3 mt-3">
            <button @click="router.push('/prozess-auftraege/neu')"
                    class="text-sm text-[#3EAAB8] hover:underline">Zur Auswahl</button>
            <button v-if="auth.isAdmin" @click="router.push('/settings?section=processes')"
                    class="text-sm text-[#3EAAB8] hover:underline">Zu den Prozessen</button>
          </div>
        </div>

        <!-- Global deaktiviert: gar kein Formular anbieten. Der Server würde das
             Anlegen ohnehin mit 409 abweisen; ein ausgefülltes Formular, das beim
             Absenden scheitert, wäre nur frustrierend. -->
        <div v-if="definition && deaktiviert"
             class="rounded-2xl border border-amber-200 dark:border-amber-500/30
                    bg-amber-50 dark:bg-amber-900/20 px-5 py-4">
          <p class="text-sm text-amber-900 dark:text-amber-200">
            Der Prozess <span class="font-medium">{{ title || selectedKey }}</span> ist derzeit
            deaktiviert – es lassen sich keine neuen Aufträge anlegen. Bitte wende dich an die
            Administration, wenn du ihn brauchst.
          </p>
          <button @click="router.push('/prozess-auftraege/neu')"
                  class="text-sm text-[#3EAAB8] hover:underline mt-3">Zur Auswahl</button>
        </div>

        <template v-if="definition && startPhase && !deaktiviert">
          <!-- Kein Prioritäts-Feld: die Priorität ist überall ausgeblendet, bis
               geklärt ist, wie sie genutzt wird (Feld bleibt in DB und API). -->
          <section class="card-section mb-4">
            <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel</label>
            <input v-model="title" class="afi w-full" maxlength="255" />
          </section>

          <SchemaForm :definition="definition" :phase="startPhase" :model-value="values"
                      :viewer="viewer" :errors="errors" :sources="sources"
                      :ticket-id="null" :pending-attachments="pendingAttachments"
                      @update:model-value="onValues($event)"
                      @update:pending-attachments="pendingAttachments = $event" />

          <div v-if="generalErrors.length"
               class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-200 mt-3">
            <div class="font-medium mb-1">Auftrag kann nicht angelegt werden:</div>
            <ul class="list-disc list-inside">
              <li v-for="(e, i) in generalErrors" :key="i">
                <span v-if="e.path !== 'body'" class="font-mono text-xs opacity-70">{{ e.path }} — </span>{{ e.message }}
              </li>
            </ul>
          </div>

          <div class="flex justify-end gap-2 mt-4">
            <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
            <button @click="submit" :disabled="submitting"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">
              {{ submitting ? 'Wird angelegt…' : 'Auftrag anlegen' }}
            </button>
          </div>
        </template>
      </template>
    </div>
  </AppLayout>
</template>
