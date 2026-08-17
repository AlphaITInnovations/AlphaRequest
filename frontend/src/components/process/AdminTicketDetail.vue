<script setup lang="ts">
/**
 * Admin-Ansicht eines Auftrags – Formation des Alt-Systems (AdminTicketDetailView):
 * Kopf mit ADMIN-Plakette und „← Zur Liste", darunter die prominente orange
 * Admin-Aktionen-Leiste (ausklappbare Werkzeuge), darunter der Read-only-Körper
 * in drei Spalten: links Fortschritt/Übersicht/Beteiligte, in der Mitte alle
 * Angaben, rechts der Verlauf.
 *
 * NUR ANZEIGE-Gate: eingehängt wird die Komponente ausschließlich für Admins
 * (?ansicht=admin) – verbindlich prüft aber JEDER Endpunkt selbst
 * (ADMIN_REQUIRED), die Oberfläche kann keine Rechte vergeben.
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import UserSelect from '@/components/UserSelect.vue'
import SchemaReadonlyView from '@/components/process/form/SchemaReadonlyView.vue'
import ProcessTimeline from '@/components/process/ProcessTimeline.vue'
import ProcessDepartments from '@/components/process/ProcessDepartments.vue'
import ProcessAttachments from '@/components/process/ProcessAttachments.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { errorMessage } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import * as ticketsApi from '@/api/processTickets'
import { reopenTicket } from '@/api/processEvents'
import type { OptionSources, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import type { SimViewer } from '@/lib/processSim'

const props = defineProps<{
  ticket: ProcessTicketOut
  definition: ProcessDefinition
  sources: OptionSources
}>()

const emit = defineEmits<{ reload: [] }>()

const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const busy = ref(false)

// ── Abgeleitetes ──────────────────────────────────────────────────────────────

const terminal = computed(() => {
  const t = props.ticket
  return t.status === 'archived' || t.status === 'rejected' || !!t.runtime?.rejected
})

const phasen = computed(() => props.definition.phases.map((p) => p.label || p.key))
const aktuellerIndex = computed(() => props.ticket.runtime?.current_index ?? 0)
const fortschrittBadge = computed(() => {
  if (props.ticket.status === 'rejected') return 'Abgelehnt'
  if (aktuellerIndex.value >= phasen.value.length) return 'Abgeschlossen'
  return `Phase ${aktuellerIndex.value + 1} von ${phasen.value.length}`
})

const gruppenName = (gid: string) =>
  props.sources.groups.find((g) => g.id === gid)?.name || gid
const personenName = (uid: string) =>
  props.sources.users.find((u) => u.id === uid)?.displayName || uid

/** Aufgelöste Zuständigkeit als lesbarer Text. */
const verantwortlich = computed(() => {
  const r = props.ticket.responsibility
  if (!r) return '—'
  if (r.kind === 'departments') {
    return r.departments.map((d) => gruppenName(d.group)).join(', ') || '—'
  }
  if (r.kind === 'group') return r.group ? gruppenName(r.group) : 'niemand'
  if (r.kind === 'user') return r.user ? personenName(r.user) : 'niemand'
  if (r.kind === 'owner') return props.ticket.owner_name || 'Ersteller:in'
  return '—'
})

/** Zuständigkeits-Feld der aktuellen Phase (nur wenn sie aus einem FELD kommt). */
const zustFeld = computed(() => {
  const r = props.ticket.responsibility as
    { kind?: string; from_field?: string | null } | null
  if (!r?.from_field) return null
  if (r.kind !== 'group' && r.kind !== 'user') return null
  return { feld: r.from_field, art: r.kind as 'group' | 'user' }
})

const fieldLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const f of props.definition.fields) out[f.key] = f.label || f.key
  return out
})
const phaseLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const p of props.definition.phases) out[p.key] = p.label || p.key
  return out
})

const viewer = computed<SimViewer>(() => ({
  fullView: false,
  isAdmin: false,
  groupIds: [],
  visibleKeys: new Set(props.ticket.visible_fields ?? []),
  editableKeys: new Set<string>(),
}))

/** Naive UTC-Zeitstempel als UTC lesen, sonst verschöbe sich die Anzeige. */
function formatiert(iso: string | null | undefined): string {
  if (!iso) return '—'
  const s = iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function fehler(e: unknown, fallback: string) {
  showToast(errorMessage(e, fallback), false)
}

// ── Zuständigkeit ändern ──────────────────────────────────────────────────────

const showZust = ref(false)
const zustSel = ref<{ id: string; name: string } | null>(null)
const zustGrund = ref('')

async function zustSpeichern() {
  const ziel = zustFeld.value
  if (!ziel || !zustSel.value) return
  if (!zustGrund.value.trim()) { showToast('Bitte eine Begründung angeben', false); return }
  busy.value = true
  try {
    // Über den Roh-Endpunkt: das Feld ist in der aktuellen Phase nicht zwingend
    // editierbar – der normale PATCH würde die Änderung still verwerfen.
    const roh = await ticketsApi.getRawValues(props.ticket.id)
    await ticketsApi.setRawValues(props.ticket.id,
      { ...roh, [ziel.feld]: zustSel.value.id }, zustGrund.value.trim())
    showZust.value = false
    zustSel.value = null
    zustGrund.value = ''
    showToast('Zuständigkeit umgestellt')
    emit('reload')
  } catch (e) {
    fehler(e, 'Zuständigkeit konnte nicht umgestellt werden')
  } finally { busy.value = false }
}

// ── Phase wechseln (aktiv) / Wiedereröffnen (terminal) ───────────────────────

const showPhase = ref(false)
const phaseZiel = ref('')
const phaseGrund = ref('')

function phaseOeffnen() {
  showPhase.value = !showPhase.value
  phaseZiel.value = props.ticket.current_phase ?? props.definition.phases[0]?.key ?? ''
  phaseGrund.value = ''
}

async function phaseSpeichern() {
  if (!phaseZiel.value) return
  if (!phaseGrund.value.trim()) { showToast('Bitte eine Begründung angeben', false); return }
  busy.value = true
  try {
    if (terminal.value) {
      await reopenTicket(props.ticket.id, phaseGrund.value.trim(), phaseZiel.value)
      showToast('Auftrag wieder aufgenommen')
    } else {
      await ticketsApi.setTicketPhase(props.ticket.id, phaseZiel.value, phaseGrund.value.trim())
      showToast('Phase umgestellt')
    }
    showPhase.value = false
    emit('reload')
  } catch (e) {
    fehler(e, 'Phase konnte nicht umgestellt werden')
  } finally { busy.value = false }
}

// ── Raw-JSON (Modal) ──────────────────────────────────────────────────────────

const showRaw = ref(false)
const rawText = ref('')
const rawGrund = ref('')
const rawError = ref('')

async function rawOeffnen() {
  rawError.value = ''
  rawGrund.value = ''
  busy.value = true
  try {
    // UNGEFILTERT laden – ein Editor auf der gefilterten Sicht würde unsichtbare
    // Alt-Schlüssel beim nächsten Speichern zerstören.
    rawText.value = JSON.stringify(await ticketsApi.getRawValues(props.ticket.id), null, 2)
    showRaw.value = true
  } catch (e) {
    fehler(e, 'Roh-Werte konnten nicht geladen werden')
  } finally { busy.value = false }
}

async function rawSpeichern() {
  let parsed: unknown
  try { parsed = JSON.parse(rawText.value || '{}') } catch {
    rawError.value = 'Kein gültiges JSON.'; return
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    rawError.value = 'Die Roh-Werte müssen ein JSON-Objekt sein.'; return
  }
  if (!rawGrund.value.trim()) { rawError.value = 'Bitte eine Begründung angeben.'; return }
  busy.value = true
  rawError.value = ''
  try {
    await ticketsApi.setRawValues(props.ticket.id,
      parsed as Record<string, unknown>, rawGrund.value.trim())
    showRaw.value = false
    showToast('Roh-Werte gespeichert')
    emit('reload')
  } catch (e) {
    rawError.value = errorMessage(e, 'Speichern fehlgeschlagen')
  } finally { busy.value = false }
}

// ── Archivieren / Löschen ─────────────────────────────────────────────────────

async function archivieren() {
  const grund = prompt('Auftrag zwangsweise abschließen – warum? (Pflicht, steht im Verlauf)')
  if (grund === null) return
  if (!grund.trim()) { showToast('Ohne Begründung kein Zwangsabschluss', false); return }
  busy.value = true
  try {
    await ticketsApi.archiveTicket(props.ticket.id, grund.trim())
    showToast('Auftrag archiviert')
    emit('reload')
  } catch (e) {
    fehler(e, 'Archivieren fehlgeschlagen')
  } finally { busy.value = false }
}

async function loeschen() {
  if (!confirm(`Auftrag #${props.ticket.id} endgültig löschen?\n\n`
    + 'Das kann NICHT rückgängig gemacht werden. Der Audit-Eintrag bleibt erhalten.')) return
  busy.value = true
  try {
    await ticketsApi.deleteTicket(props.ticket.id)
    showToast('Auftrag gelöscht')
    router.push('/auftraege')
  } catch (e) {
    fehler(e, 'Löschen fehlgeschlagen')
    busy.value = false
  }
}

// ── Verlauf nach Aktionen nachziehen ─────────────────────────────────────────
const timeline = ref<{ reload: () => void } | null>(null)

function onDepartmentsUpdated() {
  timeline.value?.reload()
  emit('reload')
}
</script>

<template>
  <div class="space-y-4">
    <!-- Kopf -->
    <div class="flex items-center justify-between gap-4 flex-wrap">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <p class="text-sm text-gray-400">Ticket #{{ ticket.id }}</p>
          <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full
                       bg-orange-100 text-orange-700 dark:bg-orange-400/15 dark:text-orange-300">
            Admin
          </span>
        </div>
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white mt-0.5 truncate">
          {{ ticket.title }}
        </h1>
      </div>
      <button @click="router.push('/auftraege')" class="btn-secondary text-sm">
        ← Zur Liste
      </button>
    </div>

    <!-- Admin-Aktionen (prominent, oben – Formation des Alt-Systems) -->
    <div class="rounded-2xl border border-orange-300/60 dark:border-orange-400/25
                bg-orange-50/70 dark:bg-orange-400/[0.07] shadow-sm p-5 space-y-4">
      <div class="flex items-center gap-2">
        <span class="text-lg leading-none">🛠️</span>
        <h2 class="font-semibold text-gray-900 dark:text-white">Admin-Aktionen</h2>
        <span class="text-xs text-gray-500 dark:text-gray-400">
          — Notfall-Werkzeuge, alle Änderungen werden protokolliert
        </span>
      </div>

      <div class="flex flex-wrap gap-2">
        <button v-if="zustFeld && !terminal" @click="showZust = !showZust" :disabled="busy"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                       bg-[#3EAAB8] hover:bg-[#2B7D89] text-white disabled:opacity-50 transition">
          👤 Zuständigkeit ändern
        </button>
        <button @click="phaseOeffnen" :disabled="busy"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                       bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50 transition">
          {{ terminal ? '🔓 Wiedereröffnen' : '🔀 Phase wechseln' }}
        </button>
        <button @click="rawOeffnen" :disabled="busy"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                       border border-gray-300 dark:border-white/15 text-gray-700 dark:text-gray-200
                       hover:bg-white dark:hover:bg-white/5 disabled:opacity-50 transition">
          🧬 Raw-JSON bearbeiten
        </button>
        <button v-if="!terminal" @click="archivieren" :disabled="busy"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                       border border-gray-300 dark:border-white/15 text-gray-700 dark:text-gray-200
                       hover:bg-white dark:hover:bg-white/5 disabled:opacity-50 transition">
          🗄️ Archivieren
        </button>
        <button @click="loeschen" :disabled="busy"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                       bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 transition ml-auto">
          🗑️ Löschen
        </button>
      </div>

      <!-- Zuständigkeit ändern (ausklappbar) -->
      <div v-if="showZust && zustFeld"
           class="rounded-xl border border-gray-200 dark:border-white/10
                  bg-white dark:bg-[#212B3A] p-4 space-y-3">
        <p class="text-xs text-gray-500 dark:text-gray-400">
          Schreibt direkt in das Zuständigkeits-Feld der aktuellen Phase
          (<span class="font-mono">{{ zustFeld.feld }}</span>) – auch wenn die Phase es
          nicht zur Bearbeitung freigibt.
        </p>
        <UserSelect v-model="zustSel" label=""
                    :placeholder="zustFeld.art === 'group'
                      ? 'Fachabteilung auswählen…' : 'Person auswählen…'"
                    :show-groups="zustFeld.art === 'group'"
                    :show-users="zustFeld.art === 'user'"
                    :groups="sources.groups" :users="sources.users" />
        <input v-model="zustGrund" class="afi w-full" maxlength="500"
               placeholder="Begründung (Pflicht – steht im Verlauf)" />
        <div class="flex justify-end gap-2">
          <button @click="showZust = false; zustSel = null" class="btn-secondary text-sm">
            Abbrechen
          </button>
          <button @click="zustSpeichern" :disabled="!zustSel || busy" class="btn-primary text-sm">
            Zuständigkeit setzen
          </button>
        </div>
      </div>

      <!-- Phase wechseln / Wiedereröffnen (ausklappbar) -->
      <div v-if="showPhase"
           class="rounded-xl border border-gray-200 dark:border-white/10
                  bg-white dark:bg-[#212B3A] p-4 space-y-3">
        <p class="text-xs text-gray-500 dark:text-gray-400">
          <template v-if="terminal">
            Abgeschlossenen/abgelehnten Auftrag in der gewählten Phase wieder aufnehmen.
          </template>
          <template v-else>
            Stellt den Auftrag auf die gewählte Phase (vor oder zurück). Die Zielphase
            wird neu betreten: Zuständigkeits-Mail und Automationen laufen erneut.
          </template>
        </p>
        <label class="block">
          <span class="text-xs text-gray-400 uppercase tracking-wider">Zielphase</span>
          <select v-model="phaseZiel" class="afi w-full mt-1">
            <option v-for="(p, i) in definition.phases" :key="p.key" :value="p.key">
              {{ i + 1 }}. {{ p.label || p.key }}
            </option>
          </select>
        </label>
        <input v-model="phaseGrund" class="afi w-full" maxlength="500"
               placeholder="Begründung (Pflicht – steht im Verlauf)" />
        <div class="flex justify-end gap-2">
          <button @click="showPhase = false" class="btn-secondary text-sm">Abbrechen</button>
          <button @click="phaseSpeichern" :disabled="busy || !phaseZiel"
                  class="btn-primary text-sm">
            {{ terminal ? 'Wiedereröffnen' : 'Phase setzen' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Fachabteilungen der aktuellen Phase (Admin darf einzeln quittieren) -->
    <ProcessDepartments
      v-if="ticket.responsibility?.kind === 'departments'"
      :ticket-id="ticket.id"
      :departments="ticket.responsibility.departments"
      :group-name="gruppenName"
      :terminal="terminal"
      @updated="onDepartmentsUpdated" />

    <!-- Read-only-Körper: drei Spalten wie im Alt-System -->
    <div class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)_360px] items-start">
      <!-- Links: Fortschritt · Übersicht · Beteiligte -->
      <div class="space-y-4">
        <div class="card-section">
          <div class="flex items-center justify-between mb-3">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Fortschritt</p>
            <span class="text-[11px] font-medium px-2 py-0.5 rounded-full
                         bg-[#3EAAB8]/10 text-[#3EAAB8]">{{ fortschrittBadge }}</span>
          </div>
          <ol class="space-y-1">
            <li v-for="(p, i) in phasen" :key="p" class="flex gap-3">
              <div class="flex flex-col items-center">
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs"
                      :class="i < aktuellerIndex || aktuellerIndex >= phasen.length
                        ? 'bg-green-500 text-white'
                        : i === aktuellerIndex && !terminal
                          ? 'bg-[#3EAAB8] text-white'
                          : 'bg-gray-200 dark:bg-white/10 text-gray-400'">
                  <svg v-if="i < aktuellerIndex || aktuellerIndex >= phasen.length"
                       class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="3">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  <span v-else-if="i === aktuellerIndex" class="w-2 h-2 rounded-full bg-white" />
                  <span v-else>{{ i + 1 }}</span>
                </span>
                <span v-if="i < phasen.length - 1"
                      class="w-px flex-1 min-h-3 bg-gray-200 dark:bg-white/10" />
              </div>
              <div class="pb-3">
                <p class="text-sm font-medium text-gray-800 dark:text-gray-100">{{ p }}</p>
                <p class="text-xs text-gray-400">
                  {{ i < aktuellerIndex || aktuellerIndex >= phasen.length ? 'Erledigt'
                     : i === aktuellerIndex ? 'Aktuell' : 'Ausstehend' }}
                </p>
              </div>
            </li>
          </ol>
        </div>

        <div class="card-section space-y-3">
          <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100">Übersicht</h3>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Status</p>
            <span class="text-xs font-medium px-2.5 py-1 rounded-full
                         bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              {{ STATUS_LABEL[ticket.status] || ticket.status }}
            </span>
          </div>
          <div v-if="ticket.current_phase_label">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Phase</p>
            <span class="text-xs font-medium px-2.5 py-1 rounded-full
                         bg-[#3EAAB8]/10 text-[#3EAAB8]">{{ ticket.current_phase_label }}</span>
          </div>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Priorität</p>
            <p class="text-sm text-gray-800 dark:text-gray-100">{{ ticket.priority }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Erstellt</p>
            <p class="text-sm text-gray-800 dark:text-gray-100">{{ formatiert(ticket.created_at) }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Geändert</p>
            <p class="text-sm text-gray-800 dark:text-gray-100">{{ formatiert(ticket.updated_at) }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Prozess</p>
            <p class="text-sm font-mono text-gray-800 dark:text-gray-100">
              {{ ticket.process_key }} v{{ ticket.process_version }}
            </p>
          </div>
        </div>

        <div class="card-section space-y-3">
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Antragsteller
            </p>
            <p class="text-sm text-gray-800 dark:text-gray-100">{{ ticket.owner_name || '—' }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Verantwortlicher
            </p>
            <p class="text-sm text-gray-800 dark:text-gray-100">{{ verantwortlich }}</p>
          </div>
        </div>
      </div>

      <!-- Mitte: alle Angaben (read-only) + Dateien -->
      <div class="space-y-4">
        <div class="card-section">
          <h3 class="section-title">Alle Angaben</h3>
          <SchemaReadonlyView :definition="definition" :values="ticket.values"
                              :viewer="viewer" :sources="sources" />
        </div>
        <div class="card-section">
          <ProcessAttachments :ticket-id="ticket.id" :can-edit="true"
                              :current-user-id="auth.user?.id ?? null" />
        </div>
      </div>

      <!-- Rechts: Verlauf -->
      <div class="card-section">
        <ProcessTimeline ref="timeline" :ticket-id="ticket.id"
                         :field-labels="fieldLabels" :phase-labels="phaseLabels"
                         :group-name="gruppenName" :can-be-internal="true" />
      </div>
    </div>

    <!-- Raw-JSON-Editor (Modal) -->
    <div v-if="showRaw" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/50" @click="showRaw = false" />
      <div class="relative w-full max-w-2xl max-h-[90vh] overflow-auto rounded-2xl
                  bg-white dark:bg-[#212B3A] border border-gray-200 dark:border-white/10
                  shadow-xl p-6 space-y-4">
        <div class="flex items-center gap-2">
          <span class="text-lg">🧬</span>
          <h3 class="font-semibold text-gray-900 dark:text-white">Raw-Bearbeitung (Notfall)</h3>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          Direkte Bearbeitung der UNGEFILTERTEN Feldwerte – Speichern ersetzt den
          gesamten Bestand. Nur mit Bedacht verwenden; es muss gültiges JSON bleiben.
        </p>
        <textarea v-model="rawText" rows="16" spellcheck="false"
                  class="afi w-full font-mono text-xs resize-y" />
        <input v-model="rawGrund" class="afi w-full" maxlength="500"
               placeholder="Begründung (Pflicht – steht im Verlauf)" />
        <p v-if="rawError" class="text-sm text-red-600 dark:text-red-400">{{ rawError }}</p>
        <div class="flex justify-end gap-2">
          <button @click="showRaw = false" class="btn-secondary text-sm">Abbrechen</button>
          <button @click="rawSpeichern" :disabled="busy" class="btn-primary text-sm">
            {{ busy ? 'Wird gespeichert…' : 'Speichern' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
