<script setup lang="ts">
/**
 * Auftrag eines dynamischen Prozesses: aktuelle Phase bearbeiten, speichern und
 * weitergeben/abschließen. Formular und Sichtbarkeit kommen aus der GEPINNTEN
 * Definition. Ablehnen, Zwangsabschluss, Wiederaufnahme und Löschen sind
 * Admin-Werkzeuge und leben im AdminActionsPanel (?ansicht=admin).
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import type { SimFieldError, SimViewer } from '@/lib/processSim'
import { validatePhaseCompletion, validateValues } from '@/lib/processSim'
import { normalizeDefinition } from '@/lib/processNormalize'
import { errorMessage, issuesFromError } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { applyComputed } from '@/lib/conditionDsl'
import * as ticketsApi from '@/api/processTickets'
import { useAuthStore } from '@/stores/authStore'
import SchemaForm from '@/components/process/form/SchemaForm.vue'
import AdminActionsPanel from '@/components/process/AdminActionsPanel.vue'
import SchemaReadonlyView from '@/components/process/form/SchemaReadonlyView.vue'
import ProcessTimeline from '@/components/process/ProcessTimeline.vue'
import ProcessWatchers from '@/components/process/ProcessWatchers.vue'
import ProcessDepartments from '@/components/process/ProcessDepartments.vue'
import BasisTicketDetail from '@/components/process/BasisTicketDetail.vue'
import { isBasisTicket } from '@/lib/basisTicket'
import SchemaExportView from '@/components/process/form/SchemaExportView.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const id = computed(() => Number(route.params.id))
const loading = ref(true)
const busy = ref(false)
const ticket = ref<ProcessTicketOut | null>(null)
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>(emptySources())
const loadError = ref<string | null>(null)

/**
 * Sichtbarkeits-Kontext für die ANZEIGE – er kommt VOM SERVER.
 *
 * Das Frontend kennt die Gruppen-Mitgliedschaft nicht und könnte die Entscheidung
 * gar nicht nachbauen. Die Antwort liefert deshalb `visible_fields` und
 * `editable_fields`; ohne sie zeigte das Formular Eingabefelder für Daten, die
 * diese Person nicht sehen darf – sie kämen leer an und der Server verwürfe die
 * Eingabe wieder.
 *
 * Fehlt die Liste ganz (unerwartet alte Antwort), wird NICHT auf Vollsicht
 * zurückgefallen: lieber ein leeres Formular als eines, das zu viel zeigt.
 */
const viewer = computed<SimViewer>(() => ({
  fullView: false,
  isAdmin: false,
  groupIds: [],
  visibleKeys: new Set(ticket.value?.visible_fields ?? []),
  editableKeys: new Set(ticket.value?.editable_fields ?? []),
}))

/** Das Basis-Ticket hat eine EIGENE, feste Ansicht im Layout des Alt-Systems –
 *  alle übrigen Prozesse rendern generisch aus der Definition. */
const istBasis = computed(() => isBasisTicket(ticket.value?.process_key))

const phase = computed(() => {
  if (!definition.value || !ticket.value) return null
  const i = ticket.value.runtime?.current_index ?? 0
  return definition.value.phases[i] ?? null
})

/** Index der aktiven Phase – Grundlage für den Fortschritts-Stepper links. */
const aktivIndex = computed(() => ticket.value?.runtime?.current_index ?? 0)

/** Ist die aktuelle Phase die LETZTE? Dann schließt der Abschluss den Auftrag ab
 *  („Abschließen"), sonst geht er an die nächste Stelle („Weitergeben"). */
const istLetztePhase = computed(() => {
  const i = ticket.value?.runtime?.current_index ?? 0
  return i >= (definition.value?.phases.length ?? 1) - 1
})
const weiterLabel = computed(() => (istLetztePhase.value ? 'Abschließen' : 'Weitergeben'))

/**
 * Erlaubte Aktionen kommen vom Server (`abilities`). Fehlt das Feld (alte
 * Antwort), wird konservativ NICHTS angeboten – lieber eine fehlende
 * Schaltfläche als eine, die mit 403 endet.
 */
const serverAbilities = computed(() => ticket.value?.abilities ?? {
  edit: false, internal_comment: false, manage_watchers: false, attach: false,
  reopen: false, archive: false, delete: false,
})

/** LESEN ist der Standard, Bearbeiten das Opt-in (?ansicht=bearbeiten): so gibt
 *  es keinen URL-Parameter, dessen ENTFERNEN mehr Oberfläche freischaltet. Den
 *  Parameter von Hand anzuhängen bringt nichts Verbotenes – die Knöpfe hängen
 *  weiter an den Server-Rechten (abilities), und verbindlich prüft ohnehin der
 *  Server jede Änderung. Die Arbeits-Reiter der Übersicht („Mir zugewiesen",
 *  „Meine Abteilungen") verlinken direkt in die Bearbeitung; „Beobachtet",
 *  „Beteiligt" und alle sonstigen Wege landen im Lesemodus. */
const leseModus = computed(() => route.query.ansicht !== 'bearbeiten')

/** Admin-Ansicht (?ansicht=admin, Einstieg über die Auftragsliste): Leseansicht
 *  PLUS Reparatur-Werkzeuge. Das isAdmin hier ist reine Anzeige – JEDER
 *  Admin-Endpunkt prüft die Rechte selbst und antwortet sonst mit 403. */
const adminModus = computed(() => route.query.ansicht === 'admin' && auth.isAdmin)

// Die Admin-Ansicht rendert eine EIGENE Komponente (AdminTicketDetail) – die
// abilities hier steuern nur noch die Lese-/Bearbeitungsansicht.
const abilities = computed(() => (leseModus.value
  ? { ...serverAbilities.value, edit: false, internal_comment: false,
      manage_watchers: false, attach: false, reopen: false, archive: false, delete: false }
  : serverAbilities.value))

// BEWUSST kein Wechsel-Knopf in der Leseansicht: in die Bearbeitung kommt man
// nur über die richtigen Einstiege (Arbeits-Reiter der Übersicht, Mail-Link).
// Die Admin-Werkzeuge leben in components/process/AdminTicketDetail.vue.

/** Beschriftungen für den Verlauf (Feld-/Phasen-Schlüssel sind nicht lesbar). */
const fieldLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const f of definition.value?.fields ?? []) out[f.key] = f.label || f.key
  return out
})
const phaseLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const p of definition.value?.phases ?? []) out[p.key] = p.label || p.key
  return out
})

/** Verlauf nach jeder Aktion neu laden (Referenz auf die Komponente). */
const timeline = ref<{ reload: () => void } | null>(null)

/** Terminal = abgelehnt/archiviert (Spiegel von process_tickets._is_terminal):
 *  dann gibt es nichts mehr zu quittieren. */
const terminal = computed(() => {
  const t = ticket.value
  return !!t && (t.status === 'archived' || t.status === 'rejected' || !!t.runtime?.rejected)
})

/** Phasen mit view='export' zeigen die Druckansicht statt der Gesamtansicht. */
const isExportPhase = computed(() => phase.value?.view === 'export')

/** Nach einer Fachabteilungs-Quittierung: Auftrag, Werte und Verlauf nachziehen –
 *  die Aktion kann den GANZEN Auftrag ablehnen (Status und Zuständigkeit ändern sich). */
function onDepartmentsUpdated(next: ProcessTicketOut) {
  ticket.value = next
  values.value = { ...(next.values || {}) }
  timeline.value?.reload()
}

const dirty = computed(() =>
  JSON.stringify(values.value) !== JSON.stringify(ticket.value?.values ?? {}))

/** Abgeleitete Felder wie auf dem Server nachziehen. */
function onValues(next: Record<string, unknown>) {
  values.value = definition.value ? applyComputed(definition.value.fields, next) : next
}

/** Fehler ohne Feldbezug (Phasen-Regeln, Server-Meldungen). */
const generalErrors = computed(() => {
  const fieldKeys = new Set(definition.value?.fields.map((f) => f.key) ?? [])
  return errors.value.filter((e) => !fieldKeys.has(e.path))
})

/** Nach Admin-Eingriffen: Auftrag UND Verlauf nachziehen. */
async function reloadAll() {
  await load()
  timeline.value?.reload()
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const t = await ticketsApi.getTicket(id.value)
    ticket.value = t
    values.value = { ...(t.values || {}) }
    // Die GEPINNTE Definition über den Ticket-Endpunkt: der Verwaltungs-Endpunkt
    // /processes/{key}/versions/{v} verlangt `manage` und würde für normale
    // Beteiligte mit 403 antworten – das Formular bliebe leer.
    definition.value = normalizeDefinition(await ticketsApi.getPinnedDefinition(id.value))
  } catch (e) {
    loadError.value = errorMessage(e, 'Auftrag konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

async function saveValues() {
  if (!definition.value) return
  const shape = validateValues(definition.value, values.value)
  if (shape.length) { errors.value = shape; showToast('Bitte Eingaben prüfen', false); return }
  busy.value = true
  try {
    ticket.value = await ticketsApi.patchTicket(id.value, { values: values.value })
    values.value = { ...(ticket.value.values || {}) }
    errors.value = []
    showToast('Gespeichert')
    // Speichern heißt: hier fertig für jetzt – zurück zur Übersicht (einheitlich
    // mit „Speichern & später weiterbearbeiten" im Basis-Ticket).
    router.push('/dashboard')
  } catch (e) {
    errors.value = issuesFromError(e).map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Speichern fehlgeschlagen'), false)
  } finally { busy.value = false }
}

async function advance() {
  if (!definition.value || !phase.value) return
  if (dirty.value) { showToast('Bitte zuerst speichern', false); return }
  const req = validatePhaseCompletion(definition.value, phase.value, values.value)
  if (req.length) { errors.value = req; showToast('Pflichtangaben fehlen', false); return }
  if (!confirm(istLetztePhase.value
    ? 'Auftrag abschließen?' : 'An die nächste Stelle weitergeben?')) return
  busy.value = true
  try {
    ticket.value = await ticketsApi.advanceTicket(id.value)
    values.value = { ...(ticket.value.values || {}) }
    errors.value = []
    showToast('Phase abgeschlossen')
    router.push('/dashboard')
  } catch (e) {
    errors.value = issuesFromError(e).map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Weiterschalten fehlgeschlagen'), false)
  } finally { busy.value = false }
}

// Ablehnen, Zwangsabschluss, Wiederaufnahme und Löschen sind Admin-Werkzeuge und
// leben ausschließlich im AdminActionsPanel (?ansicht=admin). Die normale
// Bearbeitungs-Leiste kennt nur Speichern und Weitergeben.

const groupName = (gid: string) => sources.value.groups.find((g) => g.id === gid)?.name || gid

// auth.isAdmin: normale Nutzer:innen direkt über den öffentlichen /groups-Endpunkt
// (der Admin-Endpunkt gäbe 403 – ohne Gruppennamen stünden rohe IDs in der Ansicht).
onMounted(async () => { sources.value = await loadOptionSources(auth.isAdmin); await load() })
</script>

<template>
  <AppLayout>
    <!-- Admin-Modus am breitesten (Verlauf-Spalte rechts); sonst breit genug für
         die zweispaltige Ansicht (Fortschritt-Leiste links + Formular rechts). -->
    <div class="mx-auto px-4 py-6" :class="adminModus ? 'max-w-7xl' : 'max-w-6xl'">
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <div v-else-if="loadError" class="text-sm text-red-600">{{ loadError }}</div>

      <template v-else>
        <!-- Admin-Ansicht = normale LESEANSICHT als Basis, die Aktionen-Leiste
             legt sich nur darüber. So haben alle Aufträge überall dieselbe
             Struktur; die Rechte prüft jeder Endpunkt selbst. -->
        <AdminActionsPanel v-if="adminModus && ticket && definition"
                           class="mb-4"
                           :ticket="ticket" :definition="definition" :sources="sources"
                           @reload="reloadAll" />

        <!-- Im Admin-Modus rückt der Verlauf als EIGENE Spalte rechts neben das
             normale Layout – die Reparatur braucht ihn ständig im Blick. -->
        <div :class="adminModus ? 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px] items-start' : ''">
        <div class="min-w-0">
        <!-- :key remountet die Basis-Ansicht nach Admin-Eingriffen (sie hält
             eine eigene Kopie des Auftrags und würde sonst den alten Stand zeigen). -->
        <BasisTicketDetail v-if="istBasis && ticket && definition"
                           :key="`${ticket.id}:${ticket.updated_at || ''}`"
                           :ticket="ticket" :definition="definition" :sources="sources"
                           :readonly="leseModus" />

        <template v-else-if="ticket && definition">
        <!-- Kopf: volle Breite über den zwei Spalten. -->
        <div class="mb-4 min-w-0">
          <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate">
            {{ ticket.title }}
          </h1>
          <div class="text-xs text-gray-400 flex items-center gap-2 flex-wrap">
            <span>#{{ ticket.id }}</span><span>·</span>
            <span class="font-mono">{{ ticket.process_key }} v{{ ticket.process_version }}</span>
            <span>·</span>
            <span>{{ STATUS_LABEL[ticket.status] || ticket.status }}</span>
          </div>
        </div>

        <!-- Zwei Spalten wie beim Basis-Ticket: links Fortschritt + Beobachter,
             rechts das Formular. Der Verlauf gehört NICHT hierher (nur Admin);
             „Alle Angaben" ist die Leseansicht und wird beim Bearbeiten NICHT
             doppelt gezeigt. -->
        <div class="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)] items-start">
          <!-- Linke Leiste -->
          <aside class="space-y-4 lg:sticky lg:top-4">
            <!-- Fortschritt (vertikaler Stepper) -->
            <div class="card-section">
              <div class="flex items-center justify-between mb-4">
                <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Fortschritt
                </span>
                <span class="text-[11px] font-medium px-2 py-0.5 rounded-full
                             bg-[#3EAAB8]/15 text-[#3EAAB8]">
                  Phase {{ aktivIndex + 1 }} von {{ definition.phases.length }}
                </span>
              </div>
              <ol>
                <li v-for="(p, i) in definition.phases" :key="p.key" class="flex gap-3">
                  <!-- Kreis + Verbindungslinie -->
                  <div class="flex flex-col items-center">
                    <span class="w-6 h-6 rounded-full flex items-center justify-center
                                 text-xs font-semibold shrink-0"
                          :class="i < aktivIndex ? 'bg-green-500 text-white'
                            : i === aktivIndex ? 'bg-[#3EAAB8] text-white'
                            : 'bg-gray-100 text-gray-400 dark:bg-white/10 dark:text-gray-500'">
                      <template v-if="i < aktivIndex">✓</template>
                      <template v-else>{{ i + 1 }}</template>
                    </span>
                    <span v-if="i < definition.phases.length - 1" class="w-px flex-1 my-1 min-h-[1rem]"
                          :class="i < aktivIndex ? 'bg-green-400/50' : 'bg-gray-200 dark:bg-white/10'" />
                  </div>
                  <div class="pb-3 min-w-0">
                    <p class="text-sm font-medium leading-tight"
                       :class="i === aktivIndex ? 'text-[#3EAAB8]'
                         : i < aktivIndex ? 'text-green-700 dark:text-green-300'
                         : 'text-gray-400'">
                      {{ p.label || p.key }}
                    </p>
                    <p class="text-[11px] text-gray-400">
                      {{ i < aktivIndex ? 'Erledigt' : i === aktivIndex ? 'Aktuell' : 'Ausstehend' }}
                    </p>
                  </div>
                </li>
              </ol>
              <!-- Wer ist gerade zuständig? (bewusst kompakt, read-only) -->
              <div v-if="ticket.responsibility"
                   class="text-xs text-gray-400 mt-1 pt-3 border-t border-gray-100 dark:border-white/[0.06]">
                Zuständig:
                <template v-if="ticket.responsibility.kind === 'departments'">
                  {{ ticket.responsibility.departments.map(d => groupName(d.group)).join(', ') || '—' }}
                </template>
                <template v-else-if="ticket.responsibility.kind === 'group'">
                  <span v-if="ticket.responsibility.group">
                    {{ groupName(ticket.responsibility.group) }}
                  </span>
                  <span v-else class="text-red-500 font-medium">niemand (keine Fachabteilung gewählt)</span>
                </template>
                <template v-else-if="ticket.responsibility.kind === 'owner'">
                  {{ ticket.owner_name || 'Ersteller:in' }}
                </template>
                <template v-else>—</template>
              </div>
            </div>

            <!-- Beobachter -->
            <ProcessWatchers :ticket-id="ticket.id" :current-user-id="auth.user?.id ?? null"
                             :can-manage="abilities.manage_watchers"
                             :users="sources.users" />
          </aside>

          <!-- Rechte Spalte: Arbeitsbereich -->
          <div class="min-w-0 space-y-4">
            <!-- Fachabteilungen der aktuellen Phase. Ohne diese Quittierungen
                 blockiert `:advance` mit 409 DEPARTMENT_FORBIDDEN. Bewusst
                 AUSSERHALB von abilities.edit: quittieren muss auch, wer den
                 Auftrag nicht bearbeiten darf. `terminal` unterdrückt die Knöpfe
                 in der Leseansicht und bei abgeschlossenen Aufträgen. -->
            <ProcessDepartments
              v-if="ticket.responsibility?.kind === 'departments'"
              :ticket-id="ticket.id"
              :departments="ticket.responsibility.departments"
              :group-name="groupName"
              :terminal="terminal || (leseModus && !adminModus)"
              @updated="onDepartmentsUpdated" />

            <!-- Formular der aktuellen Phase (nur für die zuständige Stelle) -->
            <template v-if="abilities.edit && phase && !isExportPhase">
              <SchemaForm :definition="definition" :phase="phase" :model-value="values"
                          :viewer="viewer" :errors="errors" :sources="sources"
                          @update:model-value="onValues($event)" />
              <!-- Nur Fehler OHNE Feldbezug: feldbezogene zeigt das Formular selbst. -->
              <div v-if="generalErrors.length"
                   class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                          px-4 py-3 text-sm text-red-800 dark:text-red-200">
                <ul class="list-disc list-inside">
                  <li v-for="(e, i) in generalErrors" :key="i">
                    <span v-if="e.path !== 'body'" class="font-mono text-xs opacity-70">{{ e.path }} — </span>{{ e.message }}
                  </li>
                </ul>
              </div>
            </template>

            <!-- Export-Phase: druckbare Zusammenfassung. Sonst die vollständige
                 Leseansicht – aber NUR, wenn nicht bearbeitet wird (beim Bearbeiten
                 zeigt das Formular die Felder bereits, kein doppeltes Rendern). -->
            <SchemaExportView
              v-if="isExportPhase"
              :definition="definition" :ticket="ticket" :phase="phase"
              :viewer="viewer" :sources="sources"
              @exported="showToast('PDF erzeugt')"
              @failed="showToast($event, false)" />
            <div v-else-if="!abilities.edit" class="card-section">
              <h3 class="section-title">Alle Angaben</h3>
              <SchemaReadonlyView :definition="definition" :values="ticket.values" :viewer="viewer"
                                  :sources="sources" />
            </div>

            <!-- KEINE allgemeine Anhang-Fläche: bei dynamischen Prozessen entstehen
                 Anhänge ausschließlich über konfigurierte Anhang-Felder
                 (widget=attachment), die das Formular oben rendert. -->
          </div>
        </div>

        <!-- Aktionsleiste – sticky, gleiches Layout wie das Basis-Ticket:
             „Abbrechen" führt immer zurück; die Schreib-Knöpfe kommen nur dazu,
             wenn bearbeitet werden darf. Ablehnen/Zwangsabschluss/Wiederaufnahme/
             Löschen sind Admin-Werkzeuge (AdminActionsPanel, ?ansicht=admin). -->
        <div class="card-section sticky bottom-4 z-20 shadow-lg mt-4
                    flex items-center justify-end gap-2 flex-wrap">
          <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
          <template v-if="abilities.edit">
            <button @click="saveValues" :disabled="busy || !dirty"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">
              Speichern &amp; später weiterbearbeiten
            </button>
            <button @click="advance" :disabled="busy"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-green-600 hover:bg-green-700
                           disabled:opacity-40 transition">
              {{ weiterLabel }}
            </button>
          </template>
        </div>
        </template>
        </div>

        <!-- Rechte Verlauf-Spalte der Admin-Ansicht (klebt beim Scrollen,
             scrollt bei langem Verlauf in sich selbst). -->
        <ProcessTimeline v-if="adminModus && ticket && definition"
                         ref="timeline" :ticket-id="ticket.id"
                         :field-labels="fieldLabels" :phase-labels="phaseLabels"
                         :group-name="groupName" :can-be-internal="true"
                         class="xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto" />
        </div>
      </template>
    </div>
  </AppLayout>
</template>
