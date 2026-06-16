<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'

const router = useRouter()
const auth   = useAuthStore()

interface TicketItem {
  id: number; title: string; type_key: string
  status: string; priority: string; created_at: string
  creator: string; responsible: string
}

const tickets  = ref<TicketItem[]>([])
const loading  = ref(true)
const selected = ref<number[]>([])

// ── Filter ──────────────────────────────────────────────────────────────────
const search            = ref('')
const statusFilter      = ref('all')
const typeFilter        = ref('all')
const responsibleFilter = ref('all')

// ── Sortierung ────────────────────────────────────────────────────────────────
type SortKey = 'id' | 'title' | 'creator' | 'responsible' | 'status' | 'priority' | 'created_at'
const sortKey = ref<SortKey>('created_at')
const sortDir = ref<'asc' | 'desc'>('desc')

// ── Client-Pagination ──────────────────────────────────────────────────────────
const pageSize = 25
const page     = ref(1)

// ── Labels & Farben ─────────────────────────────────────────────────────────
const TYPE_LABEL: Record<string, string> = {
  'hardware': 'Hardwarebestellung', 'zugang-beantragen': 'Onboarding',
  'zugang-sperren': 'Offboarding', 'niederlassung-anmelden': 'Niederlassung anmelden',
  'niederlassung-umzug': 'Niederlassung Umzug', 'niederlassung-schliessen': 'Niederlassung schließen',
  'marketing-stellenanzeige': 'Stellenanzeige', 'hotelbuchung': 'Hotelbuchung', 'basis-ticket': 'Ticket',
}
const STATUS_LABEL: Record<string, string> = {
  in_progress: 'Bearbeitung', in_request: 'Durchführung', archived: 'Erledigt', rejected: 'Abgelehnt',
}
const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  in_request:  'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  archived:    'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const PRIORITY_LABEL: Record<string, string> = { low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch' }
const PRIORITY_CLASS: Record<string, string> = {
  low: 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  medium: 'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  critical: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const STATUS_ORDER: Record<string, number>   = { in_progress: 0, in_request: 1, archived: 2, rejected: 3 }
const PRIORITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

const STATUSES = ['all', 'in_progress', 'in_request', 'archived', 'rejected']

// ── Abgeleitete Listen ──────────────────────────────────────────────────────
const typeOptions = computed(() =>
  [...new Set(tickets.value.map(t => t.type_key))].sort((a, b) =>
    (TYPE_LABEL[a] ?? a).localeCompare(TYPE_LABEL[b] ?? b)))
const responsibleOptions = computed(() =>
  [...new Set(tickets.value.map(t => t.responsible).filter(r => r && r !== '—'))].sort())

const filtered = computed(() => {
  let list = tickets.value
  if (statusFilter.value !== 'all')      list = list.filter(t => t.status === statusFilter.value)
  if (typeFilter.value !== 'all')        list = list.filter(t => t.type_key === typeFilter.value)
  if (responsibleFilter.value !== 'all') list = list.filter(t => t.responsible === responsibleFilter.value)
  const q = search.value.toLowerCase().trim()
  if (q) list = list.filter(t =>
    t.title.toLowerCase().includes(q) || t.creator.toLowerCase().includes(q) ||
    t.responsible.toLowerCase().includes(q) || String(t.id).includes(q))
  return list
})

function sortVal(t: TicketItem, k: SortKey): number | string {
  if (k === 'id')         return t.id
  if (k === 'status')     return STATUS_ORDER[t.status] ?? 99
  if (k === 'priority')   return PRIORITY_ORDER[t.priority] ?? 99
  if (k === 'created_at') return t.created_at ?? ''
  return String(t[k] ?? '').toLowerCase()
}
const sorted = computed(() => {
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...filtered.value].sort((a, b) => {
    const va = sortVal(a, sortKey.value), vb = sortVal(b, sortKey.value)
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(sorted.value.length / pageSize)))
const paged      = computed(() => sorted.value.slice((page.value - 1) * pageSize, page.value * pageSize))

watch([statusFilter, typeFilter, responsibleFilter, search, sortKey, sortDir], () => { page.value = 1 })

// ── Sortierung umschalten ──────────────────────────────────────────────────────
function setSort(k: SortKey) {
  if (sortKey.value === k) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  else { sortKey.value = k; sortDir.value = k === 'created_at' ? 'desc' : 'asc' }
}
function sortIcon(k: SortKey) { return sortKey.value !== k ? '' : sortDir.value === 'asc' ? '▲' : '▼' }

// ── Auswahl ────────────────────────────────────────────────────────────────────
const allSelected = computed(() =>
  sorted.value.length > 0 && sorted.value.every(t => selected.value.includes(t.id)))
function toggleAll(e: Event) {
  selected.value = (e.target as HTMLInputElement).checked ? sorted.value.map(t => t.id) : []
}
function toggle(id: number) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter(x => x !== id) : [...selected.value, id]
}

// ── Laden / Aktionen ───────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/overview/tickets', { params: { page: 1, page_size: 2000 } })
    tickets.value = data.data
    selected.value = []
  } finally {
    loading.value = false
  }
}

async function deleteSelected() {
  if (!selected.value.length) return
  if (!confirm(`${selected.value.length} Ticket(s) endgültig löschen?`)) return
  await Promise.all(selected.value.map(id => client.delete(`/overview/tickets/${id}`)))
  await load()
}

async function archiveSelected() {
  if (!selected.value.length) return
  if (!confirm(`${selected.value.length} Ticket(s) archivieren?`)) return
  await Promise.all(selected.value.map(id => client.post(`/overview/tickets/${id}/archive`)))
  await load()
}

function resetFilters() {
  search.value = ''; statusFilter.value = 'all'; typeFilter.value = 'all'; responsibleFilter.value = 'all'
}

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(load)
</script>

<template>
  <AppLayout title="Ticket-Übersicht">
    <div class="space-y-5">

      <!-- Header -->
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">Ticket-Übersicht</h1>
          <p class="text-sm text-gray-400 mt-0.5">{{ sorted.length }} von {{ tickets.length }} Tickets</p>
        </div>
      </div>

      <!-- Filterleiste -->
      <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                  rounded-2xl shadow-sm p-3.5 space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <button v-for="s in STATUSES" :key="s" @click="statusFilter = s"
            class="px-3 py-1.5 rounded-xl text-sm font-medium border transition"
            :class="statusFilter === s
              ? 'bg-[#3EAAB8] text-white border-[#3EAAB8]'
              : 'bg-white dark:bg-[#263040] border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8]/40'">
            {{ s === 'all' ? 'Alle' : STATUS_LABEL[s] ?? s }}
          </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto] gap-2 items-center">
          <div class="relative">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
                 fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <input v-model="search" placeholder="Titel, Ersteller, Zuständig, #ID…" class="fi !pl-10 w-full" />
          </div>
          <select v-model="typeFilter" class="fi">
            <option value="all">Alle Typen</option>
            <option v-for="tk in typeOptions" :key="tk" :value="tk">{{ TYPE_LABEL[tk] ?? tk }}</option>
          </select>
          <select v-model="responsibleFilter" class="fi">
            <option value="all">Alle Zuständigen</option>
            <option v-for="r in responsibleOptions" :key="r" :value="r">{{ r }}</option>
          </select>
          <button @click="resetFilters"
                  class="px-3 py-2 rounded-xl text-sm text-gray-500 dark:text-gray-400
                         border border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5 transition">
            Zurücksetzen
          </button>
        </div>
      </div>

      <!-- Bulk-Aktionsleiste -->
      <div v-if="selected.length > 0"
           class="flex items-center justify-between gap-3 rounded-2xl border border-[#3EAAB8]/30
                  bg-[#3EAAB8]/5 px-4 py-2.5">
        <span class="text-sm font-medium text-gray-700 dark:text-gray-200">{{ selected.length }} ausgewählt</span>
        <div class="flex items-center gap-2">
          <button v-if="auth.isAdmin" @click="archiveSelected"
                  class="px-4 py-1.5 rounded-xl bg-gray-700 hover:bg-gray-800 text-white text-sm font-medium transition">
            Archivieren
          </button>
          <button v-if="auth.canManage" @click="deleteSelected"
                  class="px-4 py-1.5 rounded-xl bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition">
            Löschen
          </button>
        </div>
      </div>

      <!-- Tabelle -->
      <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                  rounded-2xl shadow-sm overflow-hidden">
        <div v-if="loading" class="flex items-center justify-center py-16">
          <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
        </div>

        <table v-else class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-100 dark:border-white/[0.06]
                       text-xs font-semibold text-gray-400 uppercase tracking-wider select-none">
              <th v-if="auth.canManage" class="px-4 py-3 w-10 text-center">
                <input type="checkbox" :checked="allSelected" @change="toggleAll" class="rounded" />
              </th>
              <th class="th" @click="setSort('id')">ID <span class="ico">{{ sortIcon('id') }}</span></th>
              <th class="th" @click="setSort('title')">Titel <span class="ico">{{ sortIcon('title') }}</span></th>
              <th class="th" @click="setSort('creator')">Ersteller <span class="ico">{{ sortIcon('creator') }}</span></th>
              <th class="th" @click="setSort('responsible')">Zuständig <span class="ico">{{ sortIcon('responsible') }}</span></th>
              <th class="th" @click="setSort('status')">Status <span class="ico">{{ sortIcon('status') }}</span></th>
              <th class="th" @click="setSort('priority')">Priorität <span class="ico">{{ sortIcon('priority') }}</span></th>
              <th class="px-4 py-3 text-right">Aktion</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
            <tr v-for="t in paged" :key="t.id"
                @click="router.push(`/tickets/overview/${t.id}`)"
                class="hover:bg-gray-50 dark:hover:bg-[#263040] transition cursor-pointer">
              <td v-if="auth.canManage" class="px-4 py-3.5 text-center" @click.stop>
                <input type="checkbox" :checked="selected.includes(t.id)" @change="toggle(t.id)" class="rounded" />
              </td>
              <td class="px-4 py-3.5 font-mono text-xs text-[#3EAAB8]">#{{ t.id }}</td>
              <td class="px-4 py-3.5">
                <p class="font-medium text-gray-900 dark:text-white truncate max-w-xs">{{ t.title }}</p>
                <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[t.type_key] ?? t.type_key }} · {{ formatDate(t.created_at) }}</p>
              </td>
              <td class="px-4 py-3.5 text-gray-600 dark:text-gray-300">{{ t.creator }}</td>
              <td class="px-4 py-3.5 text-gray-600 dark:text-gray-300">{{ t.responsible }}</td>
              <td class="px-4 py-3.5">
                <span class="text-xs font-medium px-2.5 py-1 rounded-full"
                      :class="STATUS_CLASS[t.status] ?? 'bg-gray-100 text-gray-500'">
                  {{ STATUS_LABEL[t.status] ?? t.status }}
                </span>
              </td>
              <td class="px-4 py-3.5">
                <span class="text-xs font-medium px-2.5 py-1 rounded-full"
                      :class="PRIORITY_CLASS[t.priority] ?? 'bg-gray-100 text-gray-500'">
                  {{ PRIORITY_LABEL[t.priority] ?? t.priority }}
                </span>
              </td>
              <td class="px-4 py-3.5 text-right" @click.stop>
                <button @click="router.push(`/tickets/overview/${t.id}`)"
                        class="px-3 py-1.5 rounded-xl bg-[#3EAAB8]/10 text-[#3EAAB8]
                               hover:bg-[#3EAAB8]/20 text-xs font-medium transition">
                  Details →
                </button>
              </td>
            </tr>
            <tr v-if="paged.length === 0">
              <td :colspan="auth.canManage ? 7 : 6" class="px-4 py-12 text-center text-sm text-gray-400 italic">
                Keine Tickets gefunden
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div v-if="totalPages > 1" class="flex items-center justify-between text-sm text-gray-400">
        <span>Seite {{ page }} von {{ totalPages }}</span>
        <div class="flex gap-2">
          <button @click="page--" :disabled="page <= 1"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">← Zurück</button>
          <button @click="page++" :disabled="page >= totalPages"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">Weiter →</button>
        </div>
      </div>

    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../style.css";
.fi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
.th {
  @apply px-4 py-3 text-left cursor-pointer hover:text-[#3EAAB8] transition whitespace-nowrap;
}
.ico { @apply text-[#3EAAB8] text-[10px] ml-0.5; }
</style>
