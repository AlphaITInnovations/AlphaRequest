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
import { renderMailTemplate } from '@/lib/mailTemplate'
import * as processesApi from '@/api/processes'
import { createTicket, advanceTicket } from '@/api/processTickets'
import { uploadAttachment } from '@/api/processAttachments'
import { addWatcher } from '@/api/processEvents'
import { useAuthStore } from '@/stores/authStore'
import SchemaForm from '@/components/process/form/SchemaForm.vue'
import UserSelect from '@/components/UserSelect.vue'

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
/** Beim Anlegen gewählte Beobachter:innen (werden NACH dem Anlegen eingetragen –
 *  vorher gibt es keine Ticket-ID). Die/der Ersteller:in wird serverseitig ohnehin
 *  automatisch als Beobachter:in eingetragen und ist hier nicht wählbar. */
const pendingWatchers = ref<{ id: string; name: string }[]>([])
const watcherAuswahl = ref<{ id: string; name: string } | null>(null)

const watcherAuswaehlbar = computed(() => {
  const drin = new Set(pendingWatchers.value.map((w) => w.id))
  const self = auth.user?.id
  return (sources.value.users ?? []).filter((u) => u.id !== self && !drin.has(u.id))
})

function onWatcherAuswahl(sel: { id: string; name: string } | null) {
  if (sel && !pendingWatchers.value.some((w) => w.id === sel.id)) {
    pendingWatchers.value = [...pendingWatchers.value, { id: sel.id, name: sel.name }]
  }
  watcherAuswahl.value = null
}

function removeWatcher(watcherId: string) {
  pendingWatchers.value = pendingWatchers.value.filter((w) => w.id !== watcherId)
}

/** Anzeigename der/des Ersteller:in – ist immer Beobachter:in (fester Chip). */
const selfWatcherName = computed(() => auth.user?.displayName || auth.user?.id || 'Ich')

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

/** Live-Vorschau des Titels aus der Vorlage (falls konfiguriert). Der Server
 *  erzeugt den echten Titel; hier nur die Anzeige beim Ausfüllen. */
const titelVorschau = computed(() => {
  const tpl = definition.value?.titleTemplate
  if (!tpl) return ''
  const jetzt = new Date().toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  return renderMailTemplate(tpl, (token) => {
    if (token === 'erstellt') return jetzt
    const v = values.value[token]
    if (v === null || v === undefined || v === '') return '—'
    if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
    return Array.isArray(v) ? v.join(', ') : String(v)
  })
})

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
    pendingWatchers.value = []
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
        // Bei konfigurierter Vorlage erzeugt der Server den Titel – nichts senden.
        title: definition.value.titleTemplate ? null : (title.value || null),
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

    // Ausgewählte Beobachter:innen eintragen – der Auftrag existiert jetzt.
    // Best effort: ein Fehler hier darf das (bereits erfolgte) Anlegen nicht kippen.
    const watcherFehler: string[] = []
    for (const w of pendingWatchers.value) {
      try { await addWatcher(ticket.id, w.id) } catch { watcherFehler.push(w.name) }
    }
    if (watcherFehler.length) {
      showToast(`Nicht alle Beobachter:innen konnten eingetragen werden: ${watcherFehler.join(', ')}`, false)
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
    <div class="max-w-6xl mx-auto px-4 py-6">
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
          <!-- Zwei Spalten wie in der Detailansicht: links Fortschritt +
               Beobachter, rechts Titel + Formular. -->
          <div class="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)] items-start">
            <!-- Linke Leiste -->
            <aside class="space-y-4 lg:sticky lg:top-4">
              <!-- Fortschritt (Startphase ist aktuell) -->
              <div class="card-section">
                <div class="flex items-center justify-between mb-4">
                  <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">Fortschritt</span>
                  <span class="text-[11px] font-medium px-2 py-0.5 rounded-full bg-[#3EAAB8]/15 text-[#3EAAB8]">
                    Phase 1 von {{ definition.phases.length }}
                  </span>
                </div>
                <ol>
                  <li v-for="(p, i) in definition.phases" :key="p.key" class="flex gap-3">
                    <div class="flex flex-col items-center">
                      <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
                            :class="i === 0 ? 'bg-[#3EAAB8] text-white'
                              : 'bg-gray-100 text-gray-400 dark:bg-white/10 dark:text-gray-500'">
                        {{ i + 1 }}
                      </span>
                      <span v-if="i < definition.phases.length - 1"
                            class="w-px flex-1 my-1 min-h-[1rem] bg-gray-200 dark:bg-white/10" />
                    </div>
                    <div class="pb-3 min-w-0">
                      <p class="text-sm font-medium leading-tight"
                         :class="i === 0 ? 'text-[#3EAAB8]' : 'text-gray-400'">
                        {{ p.label || p.key }}
                      </p>
                      <p class="text-[11px] text-gray-400">{{ i === 0 ? 'Aktuell' : 'Ausstehend' }}</p>
                    </div>
                  </li>
                </ol>
              </div>

              <!-- Beobachter:innen: Auswahl wird nach dem Anlegen eingetragen. -->
              <div class="card-section">
                <h3 class="section-title mb-2">Beobachter:innen</h3>
                <ul class="flex flex-wrap gap-2 mb-2">
                  <!-- Ersteller:in ist immer Beobachter:in (serverseitig automatisch) –
                       fest vorausgewählt, nicht entfernbar. -->
                  <li class="flex items-center gap-1.5 pl-2.5 pr-2.5 py-1 rounded-full text-xs
                             bg-[#3EAAB8]/15 text-[#3EAAB8]">
                    <span>{{ selfWatcherName }}</span>
                    <span class="text-[10px] opacity-70">(Ersteller:in)</span>
                  </li>
                  <li v-for="w in pendingWatchers" :key="w.id"
                      class="flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full text-xs
                             bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200">
                    <span>{{ w.name }}</span>
                    <button type="button" @click="removeWatcher(w.id)"
                            class="text-gray-400 hover:text-red-500" :aria-label="`${w.name} entfernen`">✕</button>
                  </li>
                </ul>
                <UserSelect v-if="watcherAuswaehlbar.length" :model-value="watcherAuswahl" label=""
                            placeholder="Person suchen und hinzufügen…"
                            :show-users="true" :show-groups="false" :users="watcherAuswaehlbar"
                            @update:model-value="onWatcherAuswahl" />
                <p class="mt-2 flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400/90">
                  <svg class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24"
                       stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round"
                          d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>Beobachtende sehen <strong>alle Angaben</strong> des Auftrags.</span>
                </p>
              </div>
            </aside>

            <!-- Rechte Spalte: Titel + Formular -->
            <div class="min-w-0 space-y-4">
              <!-- Kein Prioritäts-Feld: die Priorität ist überall ausgeblendet, bis
                   geklärt ist, wie sie genutzt wird (Feld bleibt in DB und API). -->
              <section class="card-section">
                <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel</label>
                <!-- Ist im Prozess eine Titel-Vorlage hinterlegt, wird der Titel beim
                     Anlegen automatisch erzeugt – hier nur eine Live-Vorschau. -->
                <template v-if="definition.titleTemplate">
                  <div class="afi w-full bg-gray-50 dark:bg-white/[0.03] text-gray-700 dark:text-gray-200">
                    {{ titelVorschau || '—' }}
                  </div>
                  <p class="text-xs text-gray-400 mt-1">
                    Der Titel wird beim Anlegen automatisch aus der Vorlage erzeugt.
                  </p>
                </template>
                <input v-else v-model="title" class="afi w-full" maxlength="255" />
              </section>

              <SchemaForm :definition="definition" :phase="startPhase" :model-value="values"
                          :viewer="viewer" :errors="errors" :sources="sources"
                          :ticket-id="null" :pending-attachments="pendingAttachments"
                          @update:model-value="onValues($event)"
                          @update:pending-attachments="pendingAttachments = $event" />

              <div v-if="generalErrors.length"
                   class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                          px-4 py-3 text-sm text-red-800 dark:text-red-200">
                <div class="font-medium mb-1">Auftrag kann nicht angelegt werden:</div>
                <ul class="list-disc list-inside">
                  <li v-for="(e, i) in generalErrors" :key="i">
                    <span v-if="e.path !== 'body'" class="font-mono text-xs opacity-70">{{ e.path }} — </span>{{ e.message }}
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <!-- Aktionsleiste: scrollt mit dem Inhalt (bewusst NICHT sticky). -->
          <div class="flex items-center justify-end gap-2 flex-wrap mt-4">
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
