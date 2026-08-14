<script setup lang="ts">
/**
 * Ansicht eines Basis-Tickets – BEWUSST eine eigene, feste Oberfläche im Layout
 * des Alt-Systems (Gegenstück zur Anlage in views/processes/
 * BasisTicketCreateView.vue): links Fortschritt und Details (Verantwortlicher,
 * Beobachter), rechts Titel, Verlauf und „Neuer Eintrag“, unten
 * „Abbrechen · Speichern & später weiterbearbeiten · Abschließen“.
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
  edit: false, internal_comment: false, manage_watchers: false, reopen: false,
  archive: false, delete: false,
})
const terminal = computed(() => {
  const t = ticket.value
  return t.status === 'archived' || t.status === 'rejected' || !!t.runtime?.rejected
})
const darfWeiterreichen = computed(() =>
  (ticket.value.editable_fields ?? []).includes(FELD_GRUPPE) && !terminal.value)
const darfEintragen = computed(() =>
  (ticket.value.editable_fields ?? []).includes(FELD_EINTRAEGE) && !terminal.value)

const eintraege = computed<Eintrag[]>(() => {
  const v = ticket.value.values[FELD_EINTRAEGE]
  return Array.isArray(v) ? (v as Eintrag[]) : []
})

const phasen = computed(() => props.definition.phases.map((p) => p.label || p.key))
const aktuellerIndex = computed(() => ticket.value.runtime?.current_index ?? 0)
const fortschrittBadge = computed(() => {
  if (ticket.value.status === 'rejected') return 'Abgelehnt'
  if (aktuellerIndex.value >= phasen.value.length) return 'Abgeschlossen'
  return `Phase ${aktuellerIndex.value + 1} von ${phasen.value.length}`
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
  titel.value.trim() !== String(ticket.value.title || '')
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
    if (titel.value.trim() && titel.value.trim() !== String(ticket.value.title || '')) {
      body.title = titel.value.trim()
    }
    if (Object.keys(values).length) body.values = values

    if (Object.keys(body).length) {
      uebernehmen(await ticketsApi.patchTicket(ticket.value.id, body))
    }
    if (!leise) showToast('Gespeichert')
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
      <!-- Links: Fortschritt + Details -->
      <div class="card-section space-y-5">
        <div>
          <div class="flex items-center justify-between mb-3">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Fortschritt</p>
            <span class="text-[11px] font-medium px-2 py-0.5 rounded-full
                         bg-[#3EAAB8]/10 text-[#3EAAB8]">{{ fortschrittBadge }}</span>
          </div>
          <ol class="space-y-1">
            <li v-for="(p, i) in phasen" :key="p" class="flex gap-3">
              <div class="flex flex-col items-center">
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs"
                      :class="i < aktuellerIndex
                        ? 'bg-green-500 text-white'
                        : i === aktuellerIndex && !terminal
                          ? 'bg-[#3EAAB8] text-white'
                          : i === aktuellerIndex || aktuellerIndex >= phasen.length
                            ? 'bg-green-500 text-white'
                            : 'bg-gray-200 dark:bg-white/10 text-gray-400'">
                  <svg v-if="i < aktuellerIndex || aktuellerIndex >= phasen.length"
                       class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="3">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  <span v-else class="w-2 h-2 rounded-full bg-white" />
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

        <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100 border-t
                   border-gray-100 dark:border-white/[0.06] pt-4">Details</h3>

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
          <input v-model="titel" maxlength="255" class="afi w-full" :disabled="!abilities.edit" />
        </div>

        <div class="card-section">
          <h3 class="section-title">Verlauf</h3>
          <ul class="space-y-3">
            <li v-for="(e, i) in eintraege" :key="i" class="flex gap-3">
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

        <div v-if="darfEintragen" class="card-section">
          <h3 class="section-title">Neuer Eintrag</h3>
          <textarea v-model="neuerEintrag" rows="5" class="afi w-full resize-y"
                    placeholder="Ergänzende Informationen, Rückfragen, Statusupdates…" />
          <p class="text-xs text-gray-400 mt-2">
            Wird beim Speichern automatisch mit deinem Namen und Zeitstempel hinterlegt.
          </p>
        </div>
      </div>
    </div>

    <!-- Aktionsleiste -->
    <div v-if="!terminal && abilities.edit"
         class="card-section mt-4 flex items-center justify-end gap-2">
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

