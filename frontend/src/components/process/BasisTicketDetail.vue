<script setup lang="ts">
/**
 * Ansicht eines Basis-Tickets – BEWUSST eine eigene, feste Oberfläche im Layout
 * des Alt-Systems (Gegenstück zur Anlage in views/processes/
 * BasisTicketCreateView.vue): links Details (Verantwortlicher, Beobachter),
 * rechts Titel, Anhänge, „Neuer Eintrag“ und darunter der Verlauf (neueste
 * zuerst), unten – immer im Bild (sticky) – die Aktionsleiste
 * „Abbrechen · Speichern & später weiterbearbeiten · Abschließen“.
 *
 * KEINE Fortschritts-/Phasenanzeige: das Basis-Ticket wird zwischen
 * Fachabteilungen hin- und hergereicht, seine zwei internen Phasen sagen
 * nichts aus. Nur der Zustand (in Bearbeitung/abgeschlossen/abgelehnt) wird
 * als Badge gezeigt. Dynamische Prozesse behalten ihre Phasenanzeige – die
 * rendert ProcessTicketDetailView, nicht diese Komponente.
 *
 * PRIORITÄT UND KOMMENTAR sind hier bewusst NICHT setzbar: Backend und Datenbank
 * kennen beides weiterhin (PATCH `priority`, Nachtrags-Endpunkt), aber solange
 * unklar ist, wie sie sinnvoll eingesetzt werden, bietet die Oberfläche sie
 * nirgends an.
 *
 * NUR die Oberfläche ist fest – die Daten bleiben der dynamische System-Prozess:
 *   Verantwortlicher → ticket.fachabteilung (editierbar = Weiterreichen; ob das
 *                      erlaubt ist, sagt der Server über `editable_fields`)
 *   Verlauf          → ticket.eintraege (append-only; Autor und Zeitpunkt
 *                      stempelt der Server)
 *   Abschließen      → :advance (das Basis-Ticket hat danach keine weitere Phase)
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import UserSelect from '@/components/UserSelect.vue'
import ProcessAttachments from '@/components/process/ProcessAttachments.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { errorMessage, issuesFromError } from '@/lib/processErrors'
import * as ticketsApi from '@/api/processTickets'
import {
  addWatcher, listWatchers, removeWatcher, type ProcessWatcher,
} from '@/api/processEvents'
import type { OptionSources, ProcessDefinition, ProcessTicketOut } from '@/types/process'

const props = defineProps<{
  ticket: ProcessTicketOut
  definition: ProcessDefinition
  sources: OptionSources
}>()

const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

/** Eigene Kopie – die Komponente verwaltet ihre Aktionen selbst. */
const ticket = ref<ProcessTicketOut>({ ...props.ticket })
const busy = ref(false)

const FELD_GRUPPE = 'ticket.fachabteilung'
const FELD_EINTRAEGE = 'ticket.eintraege'

interface Eintrag { text?: string; author_name?: string; timestamp?: string }

const gruppenName = (gid: string) =>
  props.sources.groups.find((g) => g.id === gid)?.name || gid

function gruppeAusTicket(t: ProcessTicketOut): { id: string; name: string } | null {
  const gid = String(t.values[FELD_GRUPPE] ?? '')
  return gid ? { id: gid, name: gruppenName(gid) } : null
}

// ── Eingaben ──────────────────────────────────────────────────────────────────
const titel = ref(String(props.ticket.title || ''))
const fachabteilung = ref<{ id: string; name: string } | null>(gruppeAusTicket(props.ticket))
const neuerEintrag = ref('')

// ── Abgeleitetes ──────────────────────────────────────────────────────────────
const abilities = computed(() => ticket.value.abilities ?? {
  edit: false, internal_comment: false, manage_watchers: false, attach: false,
  reopen: false, archive: false, delete: false,
})
const terminal = computed(() => {
  const t = ticket.value
  return t.status === 'archived' || t.status === 'rejected' || !!t.runtime?.rejected
})
const darfWeiterreichen = computed(() =>
  (ticket.value.editable_fields ?? []).includes(FELD_GRUPPE) && !terminal.value)
const darfEintragen = computed(() =>
  (ticket.value.editable_fields ?? []).includes(FELD_EINTRAEGE) && !terminal.value)
/** Titel: nur änderbar, wenn die Prozess-Definition das erlaubt (das
 *  Basis-Ticket legt ihn beim Anlegen fest) – der Server weist Änderungen
 *  sonst ohnehin mit TITLE_LOCKED ab. */
const darfTitelAendern = computed(() =>
  (props.definition.titleEditable ?? true) && abilities.value.edit)

const eintraege = computed<Eintrag[]>(() => {
  const v = ticket.value.values[FELD_EINTRAEGE]
  return Array.isArray(v) ? (v as Eintrag[]) : []
})

/** Nur die ANZEIGE ist neueste zuerst – gespeichert (und beim Speichern
 *  mitgesendet) bleibt die chronologische Reihenfolge, der Server prüft
 *  append_only gegen genau die. */
const eintraegeNeuesteZuerst = computed(() => [...eintraege.value].reverse())

/** Zustand statt Phasen: „Phase 1 von 2“ sagt beim Basis-Ticket nichts. */
const statusBadge = computed(() => {
  if (ticket.value.status === 'rejected' || ticket.value.runtime?.rejected) return 'Abgelehnt'
  if (terminal.value) return 'Abgeschlossen'
  return 'In Bearbeitung'
})
const statusBadgeKlasse = computed(() => {
  if (statusBadge.value === 'Abgelehnt') return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
  if (statusBadge.value === 'Abgeschlossen') return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
  return 'bg-[#3EAAB8]/10 text-[#3EAAB8]'
})

/** Naive UTC-Zeitstempel (DB) als UTC lesen, sonst verschöbe sich die Anzeige. */
function formatiert(iso: string | null | undefined): string {
  if (!iso) return ''
  const s = iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ── Beobachter ────────────────────────────────────────────────────────────────
const beobachter = ref<ProcessWatcher[]>([])
/** Erzwingt nach jeder Auswahl einen frischen Picker (leert dessen Suchfeld). */
const pickerKey = ref(0)

const nameVon = (w: ProcessWatcher) =>
  w.name || props.sources.users.find((u) => u.id === w.id)?.displayName || w.id
const initial = (name: string) => (name.trim()[0] || '?').toUpperCase()

async function beobachterHinzu(sel: { id: string; name: string } | null) {
  pickerKey.value++
  if (!sel || beobachter.value.some((w) => w.id === sel.id)) return
  try {
    beobachter.value = await addWatcher(ticket.value.id, sel.id)
  } catch (e) {
    showToast(errorMessage(e, 'Beobachter:in konnte nicht eingetragen werden'), false)
  }
}

async function beobachterWeg(uid: string) {
  try {
    beobachter.value = await removeWatcher(ticket.value.id, uid)
  } catch (e) {
    showToast(errorMessage(e, 'Beobachtung konnte nicht beendet werden'), false)
  }
}

onMounted(async () => {
  try {
    beobachter.value = await listWatchers(ticket.value.id)
  } catch { /* Liste bleibt leer – kein Grund, die Ansicht zu kippen */ }
})

// ── Speichern / Abschließen ───────────────────────────────────────────────────
function uebernehmen(t: ProcessTicketOut) {
  ticket.value = t
  titel.value = String(t.title || '')
  fachabteilung.value = gruppeAusTicket(t)
  neuerEintrag.value = ''
}

/** Gibt es überhaupt etwas zu schreiben? */
const dirty = computed(() =>
  (darfTitelAendern.value && titel.value.trim() !== String(ticket.value.title || ''))
  || (fachabteilung.value?.id ?? '') !== String(ticket.value.values[FELD_GRUPPE] ?? '')
  || !!neuerEintrag.value.trim())

async function speichern(leise = false): Promise<boolean> {
  busy.value = true
  try {
    const values: Record<string, unknown> = {}
    if (darfWeiterreichen.value && fachabteilung.value
        && fachabteilung.value.id !== String(ticket.value.values[FELD_GRUPPE] ?? '')) {
      values[FELD_GRUPPE] = fachabteilung.value.id
    }
    if (darfEintragen.value && neuerEintrag.value.trim()) {
      // append_only: Bestand unverändert mitsenden, der Server prüft, dass nur
      // angehängt wurde, und stempelt Autor:in und Zeitpunkt des neuen Eintrags.
      values[FELD_EINTRAEGE] = [...eintraege.value, { text: neuerEintrag.value.trim() }]
    }
    const body: { title?: string; values?: Record<string, unknown> } = {}
    if (darfTitelAendern.value && titel.value.trim()
        && titel.value.trim() !== String(ticket.value.title || '')) {
      body.title = titel.value.trim()
    }
    if (Object.keys(values).length) body.values = values

    if (Object.keys(body).length) {
      uebernehmen(await ticketsApi.patchTicket(ticket.value.id, body))
    }
    if (!leise) {
      showToast('Gespeichert')
      // „Speichern & später weiterbearbeiten" heißt: hier fertig für jetzt.
      router.push('/dashboard')
    }
    return true
  } catch (e) {
    const issues = issuesFromError(e)
    showToast(issues[0]?.message || errorMessage(e, 'Speichern fehlgeschlagen'), false)
    return false
  } finally {
    busy.value = false
  }
}

async function abschliessen() {
  if (!confirm('Auftrag abschließen? Danach ist er archiviert.')) return
  if (dirty.value && !(await speichern(true))) return
  busy.value = true
  try {
    uebernehmen(await ticketsApi.advanceTicket(ticket.value.id))
    showToast('Auftrag abgeschlossen')
    router.push('/dashboard')
  } catch (e) {
    const issues = issuesFromError(e)
    showToast(issues[0]?.message || errorMessage(e, 'Abschließen fehlgeschlagen'), false)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <!-- Kopf -->
    <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
      {{ ticket.title }} – {{ formatiert(ticket.created_at) }}
    </h1>
    <p class="text-xs text-gray-400 mt-1 mb-5">Erstellt am {{ formatiert(ticket.created_at) }}</p>

    <div class="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr] items-start">
      <!-- Links: Details (bewusst OHNE Fortschritt/Phasen – siehe Kopfkommentar) -->
      <div class="card-section space-y-5">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100">Details</h3>
          <span class="text-[11px] font-medium px-2 py-0.5 rounded-full"
                :class="statusBadgeKlasse">{{ statusBadge }}</span>
        </div>

        <div>
          <!-- Editierbar = Weiterreichen (das Feld trägt die Zuständigkeit); ob das
               erlaubt ist, entscheidet der Server über editable_fields. -->
          <UserSelect v-if="darfWeiterreichen" v-model="fachabteilung"
                      label="Verantwortlicher"
                      placeholder="Fachabteilung auswählen…"
                      :show-groups="true" :show-users="false" />
          <template v-else>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Verantwortlicher
            </label>
            <div class="afi w-full !bg-gray-50 dark:!bg-white/[0.04]">
              {{ fachabteilung?.name || '— niemand zugewiesen —' }}
            </div>
          </template>
        </div>

        <div>
          <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Beobachter</p>
          <ul class="space-y-1.5 mb-2">
            <li v-for="w in beobachter" :key="w.id"
                class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
              <span class="w-6 h-6 rounded-full bg-[#3EAAB8]/15 text-[#3EAAB8]
                           flex items-center justify-center text-xs font-semibold">
                {{ initial(nameVon(w)) }}
              </span>
              <span class="truncate">{{ nameVon(w) }}</span>
              <button v-if="abilities.manage_watchers || w.id === auth.user?.id"
                      @click="beobachterWeg(w.id)"
                      class="ml-auto text-gray-300 hover:text-red-500 transition"
                      :aria-label="`${nameVon(w)} entfernen`">✕</button>
            </li>
            <li v-if="!beobachter.length" class="text-sm text-gray-400 italic">
              Niemand beobachtet diesen Auftrag.
            </li>
          </ul>
          <UserSelect v-if="abilities.manage_watchers || !terminal"
                      :key="pickerKey" :model-value="null" label=""
                      placeholder="Beobachter hinzufügen…"
                      @update:model-value="beobachterHinzu" />
        </div>
      </div>

      <!-- Rechts: Titel, Verlauf, Neuer Eintrag -->
      <div class="space-y-4">
        <div class="card-section">
          <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">Titel</label>
          <input v-if="darfTitelAendern" v-model="titel" maxlength="255" class="afi w-full" />
          <div v-else class="afi w-full !bg-gray-50 dark:!bg-white/[0.04]">
            {{ ticket.title }}
          </div>
        </div>

        <!-- Anhänge: hochladen darf die zuständige Stelle UND die Ersteller:in
             (Unterlagen nachreichen) – das entscheidet der Server (abilities). -->
        <div class="card-section">
          <ProcessAttachments :ticket-id="ticket.id" :can-edit="abilities.edit"
                              :can-attach="abilities.attach"
                              :current-user-id="auth.user?.id ?? null" />
        </div>

        <div v-if="darfEintragen" class="card-section">
          <h3 class="section-title">Neuer Eintrag</h3>
          <textarea v-model="neuerEintrag" rows="5" class="afi w-full resize-y"
                    placeholder="Ergänzende Informationen, Rückfragen, Statusupdates…" />
          <p class="text-xs text-gray-400 mt-2">
            Wird beim Speichern automatisch mit deinem Namen und Zeitstempel hinterlegt.
          </p>
        </div>

        <div class="card-section">
          <h3 class="section-title">Verlauf</h3>
          <!-- Neueste zuerst – der frischeste Stand steht direkt unter dem Eingabefeld. -->
          <ul class="space-y-3">
            <li v-for="(e, i) in eintraegeNeuesteZuerst" :key="i" class="flex gap-3">
              <span class="w-2 h-2 rounded-full bg-[#3EAAB8] mt-2 flex-shrink-0" />
              <div class="flex-1 rounded-xl border border-gray-100 dark:border-white/[0.06]
                          px-4 py-3">
                <div class="flex items-baseline justify-between gap-3 flex-wrap">
                  <p class="text-sm font-semibold text-gray-800 dark:text-gray-100">
                    {{ e.author_name || '—' }}
                  </p>
                  <p class="text-xs text-gray-400">{{ formatiert(e.timestamp) }}</p>
                </div>
                <p class="text-sm text-gray-700 dark:text-gray-200 mt-1 whitespace-pre-wrap">
                  {{ e.text }}
                </p>
              </div>
            </li>
            <li v-if="!eintraege.length" class="text-sm text-gray-400 italic">
              Noch keine Einträge.
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Aktionsleiste – sticky: bleibt beim Scrollen immer im Bild (der lange
         Verlauf darf die Knöpfe nicht aus dem Fenster schieben). -->
    <div v-if="!terminal && abilities.edit"
         class="card-section sticky bottom-4 z-20 shadow-lg mt-4
                flex items-center justify-end gap-2">
      <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
      <button @click="speichern()" :disabled="busy || !dirty"
              class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                     disabled:opacity-40 transition">
        Speichern &amp; später weiterbearbeiten
      </button>
      <button @click="abschliessen" :disabled="busy"
              class="px-4 py-2 rounded-xl text-sm text-white bg-green-600 hover:bg-green-700
                     disabled:opacity-40 transition">
        Abschließen
      </button>
    </div>
  </div>
</template>

