<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'

const router = useRouter()
const auth   = useAuthStore()

interface TicketItem {
  id: number; title: string; type_key: string
  status: string; priority: string; created_at: string; creator: string
}

const tickets  = ref<TicketItem[]>([])
const total    = ref(0)
const loading  = ref(true)
const page     = ref(1)
const pageSize = 50

const search   = ref('')
const filter   = ref('all')
const selected = ref<number[]>([])

const STATUSES = ['all', 'in_request', 'in_progress', 'archived', 'rejected']

const STATUS_LABEL: Record<string, string> = {
  in_request: 'Zu bearbeiten', in_progress: 'In Bearbeitung',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const STATUS_CLASS: Record<string, string> = {
  in_request:  'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  in_progress: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  archived:    'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const PRIORITY_CLASS: Record<string, string> = {
  low:      'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  medium:   'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  high:     'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  critical: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}

const totalPages = computed(() => Math.ceil(total.value / pageSize) || 1)

const filtered = computed(() => {
  let list = filter.value === 'all' ? tickets.value : tickets.value.filter(t => t.status === filter.value)
  const q = search.value.toLowerCase().trim()
  if (q) list = list.filter(t =>
    t.title.toLowerCase().includes(q) ||
    t.creator.toLowerCase().includes(q) ||
    String(t.id).includes(q)
  )
  return list
})

const allSelected = computed(() =>
  filtered.value.length > 0 && filtered.value.every(t => selected.value.includes(t.id))
)

function toggleAll(e: Event) {
  selected.value = (e.target as HTMLInputElement).checked
    ? filtered.value.map(t => t.id)
    : []
}

function toggle(id: number) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter(x => x !== id)
    : [...selected.value, id]
}

async function loadPage() {
  loading.value = true
  try {
    const { data } = await client.get('/overview/tickets', {
      params: { page: page.value, page_size: pageSize }
    })
    tickets.value = data.data
    total.value   = data.meta.total
    selected.value = []
  } finally {
    loading.value = false
  }
}

async function deleteSelected() {
  if (!selected.value.length) return
  if (!confirm(`${selected.value.length} Ticket(s) wirklich löschen?`)) return
  await Promise.all(selected.value.map(id => client.delete(`/overview/tickets/${id}`)))
  await loadPage()
}

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })
}

onMounted(loadPage)
</script>

<template>
  <AppLayout title="Ticket-Übersicht">
    <div class="space-y-5">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">Ticket-Übersicht</h1>
          <p class="text-sm text-gray-400 mt-0.5">{{ total }} Tickets gesamt</p>
        </div>
        <button
          v-if="auth.canManage"
          @click="deleteSelected"
          :disabled="selected.length === 0"
          class="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-sm font-medium
                 transition disabled:opacity-40 disabled:cursor-not-allowed">
          Löschen ({{ selected.length }})
        </button>
      </div>

      <!-- Filter + Suche -->
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="s in STATUSES" :key="s"
          @click="filter = s"
          class="px-3 py-1.5 rounded-xl text-sm font-medium border transition"
          :class="filter === s
            ? 'bg-[#3EAAB8] text-white border-[#3EAAB8]'
            : 'bg-white dark:bg-[#212B3A] border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8]/40'"
        >
          {{ s === 'all' ? 'Alle' : STATUS_LABEL[s] ?? s }}
        </button>

        <input
          v-model="search"
          placeholder="Suchen…"
          class="ml-auto rounded-xl border border-gray-200 dark:border-white/10
                 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                 px-3.5 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30"
        />
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
                       text-xs font-semibold text-gray-400 uppercase tracking-wider">
              <th v-if="auth.canManage" class="px-4 py-3 w-10 text-center">
                <input type="checkbox" :checked="allSelected" @change="toggleAll" class="rounded" />
              </th>
              <th class="px-4 py-3 text-left">ID</th>
              <th class="px-4 py-3 text-left">Titel</th>
              <th class="px-4 py-3 text-left">Ersteller</th>
              <th class="px-4 py-3 text-left">Status</th>
              <th class="px-4 py-3 text-left">Priorität</th>
              <th class="px-4 py-3 text-right">Aktion</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
            <tr v-for="t in filtered" :key="t.id"
                class="hover:bg-gray-50 dark:hover:bg-[#263040] transition group">
              <td v-if="auth.canManage" class="px-4 py-3.5 text-center">
                <input type="checkbox" :checked="selected.includes(t.id)" @change="toggle(t.id)" class="rounded" />
              </td>
              <td class="px-4 py-3.5 font-mono text-xs text-[#3EAAB8]">#{{ t.id }}</td>
              <td class="px-4 py-3.5">
                <p class="font-medium text-gray-900 dark:text-white truncate max-w-xs">{{ t.title }}</p>
                <p class="text-xs text-gray-400 mt-0.5">{{ formatDate(t.created_at) }}</p>
              </td>
              <td class="px-4 py-3.5 text-gray-600 dark:text-gray-300">{{ t.creator }}</td>
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
              <td class="px-4 py-3.5 text-right">
                <button @click="router.push(`/tickets/overview/${t.id}`)"
                        class="px-3 py-1.5 rounded-xl bg-[#3EAAB8]/10 text-[#3EAAB8]
                               hover:bg-[#3EAAB8]/20 text-xs font-medium transition">
                  Details →
                </button>
              </td>
            </tr>
            <tr v-if="filtered.length === 0">
              <td :colspan="auth.canManage ? 7 : 6"
                  class="px-4 py-12 text-center text-sm text-gray-400 italic">
                Keine Tickets gefunden
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between text-sm text-gray-400">
        <span>Seite {{ page }} von {{ totalPages }}</span>
        <div class="flex gap-2">
          <button @click="page--; loadPage()" :disabled="page <= 1"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">
            ← Zurück
          </button>
          <button @click="page++; loadPage()" :disabled="page >= totalPages"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">
            Weiter →
          </button>
        </div>
      </div>

    </div>
  </AppLayout>
</template>