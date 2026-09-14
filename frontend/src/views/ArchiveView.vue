<script setup lang="ts">
/**
 * Persönliches Archiv: alle Aufträge (jeder Status), an denen ich je beteiligt
 * war – als Ersteller:in, Beobachter:in, Zuständige:r oder als Mitglied einer
 * Fachabteilung/Gruppe, die im Prozess zuständig ist (auch rückwirkend: neue
 * Mitglieder sehen die Vergangenheit). Wer WAS sieht, entscheidet der Server:
 * die Liste trägt keine Feldwerte, die Detail-Ansicht filtert nach Sichtbarkeit
 * und zeigt keinen Verlauf.
 *
 * Serverseitiges Paging (die Beteiligungsprüfung läuft pro Auftrag).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { listArchive, type ArchiveRow } from '@/api/archive'
import { archiveTicket, deleteTicket } from '@/api/processTickets'
import { listProcesses } from '@/api/processes'
import { STATUS_LABEL } from '@/lib/processSchema'
import { errorMessage } from '@/lib/processErrors'

const props = withDefaults(defineProps<{ scope?: 'mine' | 'global' }>(), { scope: 'mine' })
const isGlobal = computed(() => props.scope === 'global')

const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const PAGE = 25
const items = ref<ArchiveRow[]>([])
const total = ref(0)
const offset = ref(0)
const truncated = ref(false)
const loading = ref(true)
const q = ref('')

/** Filter (wie „Alle Aufträge"): Status-Chips (leer = alle), Prozess-Dropdown. */
const ARCHIVE_STATUSES = ['in_progress', 'in_request', 'waiting_contract', 'archived', 'rejected']
const statuses = ref<string[]>([])
const processKey = ref('')
const katalog = ref<{ key: string; name: string }[]>([])

function toggleStatus(s: string) {
  statuses.value = statuses.value.includes(s)
    ? statuses.value.filter((x) => x !== s)
    : [...statuses.value, s]
}
function reset() { statuses.value = []; processKey.value = ''; q.value = '' }
const hatFilter = computed(() => !!(statuses.value.length || processKey.value || q.value.trim()))

const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  in_request: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  waiting_contract: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  archived: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const statusLabel = (s: string) => STATUS_LABEL[s] ?? s
const statusClass = (s: string) =>
  STATUS_CLASS[s] ?? 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400'

const terminal = (s: string) => s === 'archived' || s === 'rejected'

// ── Admin-Sammelaktionen (NUR im globalen Archiv) ────────────────────────────
// Auswahl per Kästchen + Archivieren/Löschen für alle Markierten. Ausschließlich
// für Admins; die Aktionen laufen über die bestehenden, pro Auftrag geprüften und
// auditierten Einzel-Endpunkte (kein ungeprüfter Sammel-Endpunkt).
const canBulk = computed(() => isGlobal.value && auth.isAdmin)
const selected = ref<Set<number>>(new Set())
const busy = ref(false)
const confirmAction = ref<null | 'archive' | 'delete'>(null)

const isSel = (id: number) => selected.value.has(id)
const allSelected = computed(() =>
  items.value.length > 0 && items.value.every((r) => selected.value.has(r.id)))
const someSelected = computed(() => items.value.some((r) => selected.value.has(r.id)))

function toggleOne(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(items.value.map((r) => r.id))
}
function clearSelection() { selected.value = new Set() }

function askBulk(kind: 'archive' | 'delete') { if (selected.value.size) confirmAction.value = kind }

async function runBulk() {
  const kind = confirmAction.value
  confirmAction.value = null
  if (!kind) return
  busy.value = true
  let ok = 0, skipped = 0, failed = 0
  // Über die aktuelle Seite laufen (nur sichtbare Zeilen sind wählbar).
  for (const r of items.value) {
    if (!selected.value.has(r.id)) continue
    try {
      if (kind === 'archive') {
        if (terminal(r.status)) { skipped++; continue }   // schon abgeschlossen
        await archiveTicket(r.id, 'Sammel-Archivierung über das globale Archiv')
      } else {
        await deleteTicket(r.id)
      }
      ok++
    } catch { failed++ }
  }
  busy.value = false
  const parts = [kind === 'archive' ? `${ok} archiviert` : `${ok} gelöscht`]
  if (skipped) parts.push(`${skipped} übersprungen (bereits abgeschlossen)`)
  if (failed) parts.push(`${failed} fehlgeschlagen`)
  showToast(parts.join(' · '), failed === 0)
  await load()   // lädt neu und leert die Auswahl
}

const von = computed(() => (total.value === 0 ? 0 : offset.value + 1))
const bis = computed(() => Math.min(offset.value + PAGE, total.value))
const hatVor = computed(() => offset.value > 0)
const hatWeiter = computed(() => offset.value + PAGE < total.value)

// Anti-Stale-Guard: bei schnellem Wechsel (Scope/Filter) dürfen überholte
// Antworten die neueren nicht überschreiben.
let reqSeq = 0
async function load() {
  const mine = ++reqSeq
  loading.value = true
  try {
    const page = await listArchive({
      scope: props.scope,
      q: q.value.trim() || undefined,
      status: statuses.value.length ? statuses.value : undefined,
      process_key: processKey.value || undefined,
      limit: PAGE, offset: offset.value,
    })
    if (mine !== reqSeq) return
    items.value = page.items
    total.value = page.total
    truncated.value = page.truncated
    selected.value = new Set()   // Auswahl gilt je Seite/Filter – bei neuem Stand leeren
  } catch (e) {
    if (mine !== reqSeq) return
    showToast(errorMessage(e, 'Archiv konnte nicht geladen werden'), false)
    items.value = []
    total.value = 0
  } finally {
    if (mine === reqSeq) loading.value = false
  }
}

function open(row: ArchiveRow) {
  // Archiv = Lesen. Im GLOBALEN Archiv öffnen Admins die Admin-Ansicht (Lesen +
  // Reparatur-Werkzeuge), viewer/manager die normale Leseansicht (wie das alte
  // „Alle Aufträge"). Rechte vergibt der Parameter nicht – der Server prüft je Auftrag.
  const ansicht = isGlobal.value && auth.isAdmin ? 'admin' : 'lesen'
  router.push(`/prozess-auftraege/${row.id}?ansicht=${ansicht}`)
}

function vor() { if (hatVor.value) { offset.value = Math.max(0, offset.value - PAGE); load() } }
function weiter() { if (hatWeiter.value) { offset.value += PAGE; load() } }

// Suche: bei Eingabe zurück auf Seite 1 (entprellt).
let suchTimer: ReturnType<typeof setTimeout> | null = null
watch(q, () => {
  if (suchTimer) clearTimeout(suchTimer)
  suchTimer = setTimeout(() => { offset.value = 0; load() }, 300)
})
// Status/Prozess: sofort neu laden (zurück auf Seite 1).
watch([statuses, processKey], () => { offset.value = 0; load() })
// Reichweite gewechselt (persönlich ↔ global): Vue Router verwendet DIESELBE
// Komponente wieder, onMounted läuft nicht erneut. Beide Archive sind unabhängig →
// Filter/Seite zurücksetzen und mit dem neuen Scope frisch laden.
watch(() => props.scope, () => {
  statuses.value = []
  processKey.value = ''
  q.value = ''
  offset.value = 0
  load()
})

onMounted(async () => {
  // Prozess-Dropdown befüllen (fail-soft: ohne Katalog bleibt nur „Alle Prozesse").
  try {
    katalog.value = (await listProcesses()).map((p) => ({ key: p.key, name: p.name }))
  } catch { /* Prozess-Filter bleibt leer */ }
  await load()
})
</script>

<template>
  <AppLayout>
    <div class="max-w-5xl mx-auto px-4 py-6">
      <div class="flex items-end justify-between gap-3 flex-wrap mb-4">
        <div>
          <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">
            {{ isGlobal ? 'Globales Archiv' : 'Persönliches Archiv' }}
          </h1>
          <p class="text-sm text-gray-500 dark:text-gray-400">
            {{ isGlobal ? 'Alle Aufträge im System.' : 'Deine Auftrags-Historie.' }}
          </p>
        </div>
        <input v-model="q" type="search" placeholder="Nach Titel suchen…"
               class="afi w-full sm:w-64" />
      </div>

      <!-- Kompakte Info: welche Aufträge hier erscheinen. -->
      <div class="mb-4 rounded-xl border border-gray-200/80 dark:border-white/[0.09]
                  bg-gray-50 dark:bg-white/[0.03] px-4 py-2.5 flex items-start gap-2">
        <svg class="w-4 h-4 flex-shrink-0 text-[#3EAAB8] mt-0.5" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/>
          <line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/>
        </svg>
        <p v-if="isGlobal" class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
          <strong>Alle Aufträge im System</strong> (Aufsicht). Du siehst nur die Abschnitte,
          für die du berechtigt bist – die Feld-Sichtbarkeit gilt auch hier.
        </p>
        <p v-else class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
          Hier stehen alle Aufträge, an denen <strong>du</strong> beteiligt warst – als
          <strong>Ersteller:in</strong>, <strong>Beobachter:in</strong>,
          <strong>zuständige Stelle</strong> oder als Mitglied einer beteiligten
          <strong>Fachabteilung</strong> (auch rückwirkend). Du siehst nur die Abschnitte,
          für die du berechtigt bist.
        </p>
      </div>

      <!-- Filter wie „Alle Aufträge": Status-Chips (keiner aktiv = alle) + Prozess. -->
      <div class="flex items-center gap-2 flex-wrap mb-4">
        <button v-for="s in ARCHIVE_STATUSES" :key="s" type="button" @click="toggleStatus(s)"
                class="text-xs font-medium px-2.5 py-1 rounded-full border transition"
                :class="statuses.includes(s)
                  ? 'bg-[#3EAAB8] text-white border-[#3EAAB8]'
                  : 'border-gray-200 dark:border-white/15 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'">
          {{ statusLabel(s) }}
        </button>
        <select v-model="processKey" class="afi !py-1 text-sm w-auto ml-auto">
          <option value="">Alle Prozesse</option>
          <option v-for="p in katalog" :key="p.key" :value="p.key">{{ p.name }}</option>
        </select>
        <button v-if="hatFilter" type="button" @click="reset"
                class="text-xs text-gray-500 dark:text-gray-400 hover:underline">
          Filter zurücksetzen
        </button>
      </div>

      <div v-if="truncated"
           class="mb-3 rounded-xl border border-amber-200 dark:border-amber-500/30
                  bg-amber-50 dark:bg-amber-900/20 px-4 py-2.5 text-xs text-amber-800 dark:text-amber-200">
        Es gibt sehr viele Aufträge – es werden die neuesten angezeigt. Grenze die Suche ein,
        um ältere zu finden.
      </div>

      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <template v-else>
        <p v-if="!items.length" class="text-sm text-gray-400 italic py-10 text-center">
          {{ hatFilter ? 'Keine Treffer für diese Filter.'
             : (isGlobal ? 'Noch keine Aufträge im System.' : 'Du warst bisher an keinem Auftrag beteiligt.') }}
        </p>

        <!-- Admin-Sammelaktionen (nur globales Archiv): Auswahl + Aktionen. -->
        <div v-if="canBulk && items.length" class="flex items-center gap-3 flex-wrap mb-2 px-1">
          <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300 cursor-pointer select-none">
            <input type="checkbox" class="h-4 w-4 rounded border-gray-300 dark:border-white/20 accent-[#3EAAB8]"
                   :checked="allSelected" :indeterminate="someSelected && !allSelected" @change="toggleAll" />
            Alle auf dieser Seite
          </label>
          <template v-if="selected.size">
            <span class="text-xs text-gray-500 dark:text-gray-400">{{ selected.size }} ausgewählt</span>
            <button type="button" @click="askBulk('archive')" :disabled="busy"
                    class="text-xs font-medium px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/15
                           text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/5 disabled:opacity-40">
              Archivieren
            </button>
            <button type="button" @click="askBulk('delete')" :disabled="busy"
                    class="text-xs font-medium px-2.5 py-1 rounded-lg border border-red-200 dark:border-red-500/30
                           text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40">
              Löschen
            </button>
            <button type="button" @click="clearSelection"
                    class="text-xs text-gray-400 hover:underline">Auswahl aufheben</button>
          </template>
        </div>

        <ul v-if="items.length" class="flex flex-col gap-2">
          <li v-for="r in items" :key="r.id"
              @click="open(r)"
              class="cursor-pointer flex items-start gap-3 px-4 py-3.5 rounded-xl
                     bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                     hover:border-[#3EAAB8]/40 hover:shadow-sm hover:-translate-y-px transition"
              :class="isSel(r.id) ? 'ring-1 ring-[#3EAAB8]/50' : ''">
            <input v-if="canBulk" type="checkbox" :checked="isSel(r.id)"
                   @click.stop @change="toggleOne(r.id)"
                   class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 dark:border-white/20 accent-[#3EAAB8] cursor-pointer" />
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
                {{ r.title || `Auftrag #${r.id}` }}
              </p>
              <div class="text-xs text-gray-400 flex items-center gap-2 flex-wrap mt-0.5">
                <span>#{{ r.id }}</span>
                <span v-if="r.is_owner" class="text-[#3EAAB8]">· von mir angelegt</span>
                <span v-if="!terminal(r.status) && r.phase_label">· {{ r.phase_label }}</span>
                <span>· aktualisiert {{ r.updated_at }}</span>
              </div>
            </div>
            <span class="text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
                  :class="statusClass(r.status)">{{ statusLabel(r.status) }}</span>
          </li>
        </ul>

        <!-- Pager -->
        <div v-if="total > 0" class="flex items-center justify-between gap-3 mt-4 flex-wrap">
          <span class="text-xs text-gray-500 dark:text-gray-400">{{ von }}–{{ bis }} von {{ total }}</span>
          <div class="flex items-center gap-2">
            <button @click="vor" :disabled="!hatVor" class="btn-secondary text-sm disabled:opacity-40">
              Zurück
            </button>
            <button @click="weiter" :disabled="!hatWeiter" class="btn-secondary text-sm disabled:opacity-40">
              Weiter
            </button>
          </div>
        </div>
      </template>

      <!-- Bestätigung der Sammelaktion (Löschen ist endgültig). -->
      <div v-if="confirmAction" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
           @click.self="confirmAction = null">
        <div class="w-full max-w-md rounded-2xl bg-white dark:bg-[#212B3A] shadow-xl p-5">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white mb-2">
            {{ confirmAction === 'delete' ? `${selected.size} Aufträge löschen?` : `${selected.size} Aufträge archivieren?` }}
          </h3>
          <p class="text-sm text-gray-600 dark:text-gray-300">
            <template v-if="confirmAction === 'delete'">
              Die ausgewählten Aufträge werden <strong>endgültig gelöscht</strong> – das lässt
              sich <strong>nicht rückgängig</strong> machen.
            </template>
            <template v-else>
              Die ausgewählten Aufträge werden zwangsweise abgeschlossen (archiviert). Bereits
              abgeschlossene werden übersprungen; rückholbar über die Wiederaufnahme.
            </template>
          </p>
          <div class="flex justify-end gap-2 mt-5">
            <button type="button" @click="confirmAction = null" class="btn-secondary text-sm">Abbrechen</button>
            <button type="button" @click="runBulk" :disabled="busy"
                    class="text-sm font-medium px-4 py-2 rounded-xl text-white disabled:opacity-50"
                    :class="confirmAction === 'delete' ? 'bg-red-600 hover:bg-red-700' : 'bg-[#3EAAB8] hover:bg-[#369aa7]'">
              {{ confirmAction === 'delete' ? 'Endgültig löschen' : 'Archivieren' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
