<script setup lang="ts">
/** Übersicht der Aufträge aus dynamischen Prozessen. */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import type { ProcessOut, ProcessTicketOut } from '@/types/process'
import { STATUS_LABEL } from '@/lib/processSchema'
import { errorMessage } from '@/lib/processErrors'
import { listTickets } from '@/api/processTickets'
import { listProcesses } from '@/api/processes'

const router = useRouter()
const loading = ref(false)
const items = ref<ProcessTicketOut[]>([])
const total = ref(0)
const catalog = ref<ProcessOut[]>([])
const loadError = ref<string | null>(null)

const q = ref('')
const fStatus = ref('')
const fProcess = ref('')
const pageSize = 25
const offset = ref(0)

const page = computed(() => Math.floor(offset.value / pageSize) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  in_request: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  waiting_contract: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  archived: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}

function formatDate(ts: string | null) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  loadError.value = null
  try {
    const res = await listTickets({
      limit: pageSize, offset: offset.value,
      q: q.value || undefined,
      status: fStatus.value || undefined,
      process_key: fProcess.value || undefined,
    })
    if (my !== reqId) return
    items.value = res.items
    total.value = res.total
  } catch (e) {
    loadError.value = errorMessage(e, 'Aufträge konnten nicht geladen werden')
  } finally {
    if (my === reqId) loading.value = false
  }
}

let debounce: ReturnType<typeof setTimeout> | null = null
watch([q, fStatus, fProcess], () => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => { offset.value = 0; load() }, 250)
})
watch(offset, load)

onMounted(async () => {
  try { catalog.value = await listProcesses() } catch { /* Filter bleibt leer */ }
  load()
})
</script>

<template>
  <AppLayout>
    <div class="max-w-7xl mx-auto px-4 py-6">
      <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
        <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">Prozess-Aufträge</h1>
        <button @click="router.push('/prozess-auftraege/neu')"
                class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7] transition">
          Neuer Auftrag
        </button>
      </div>

      <div class="flex flex-wrap gap-2 items-center mb-3">
        <input v-model="q" placeholder="Suche im Titel…" class="afi flex-1 min-w-[12rem]" />
        <select v-model="fProcess" class="afi">
          <option value="">Alle Prozesse</option>
          <option v-for="p in catalog" :key="p.key" :value="p.key">{{ p.name }}</option>
        </select>
        <select v-model="fStatus" class="afi">
          <option value="">Alle Status</option>
          <option v-for="(lbl, key) in STATUS_LABEL" :key="key" :value="key">{{ lbl }}</option>
        </select>
      </div>

      <div v-if="loadError" class="text-sm text-red-600 mb-3">{{ loadError }}</div>

      <div class="card-section !p-0 overflow-hidden">
        <div v-if="loading && !items.length" class="flex items-center justify-center py-16">
          <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
        </div>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-gray-400 uppercase tracking-wider border-b dark:border-white/[0.06]">
              <th class="px-4 py-3">Titel</th>
              <th class="px-4 py-3">Prozess</th>
              <th class="px-4 py-3">Phase</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3">Geändert</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
            <tr v-for="t in items" :key="t.id"
                @click="router.push(`/prozess-auftraege/${t.id}`)"
                class="hover:bg-gray-50 dark:hover:bg-[#263040] transition cursor-pointer">
              <td class="px-4 py-3 text-gray-800 dark:text-gray-100">
                {{ t.title }} <span class="text-gray-400 text-xs">#{{ t.id }}</span>
              </td>
              <td class="px-4 py-3 text-gray-600 dark:text-gray-300 font-mono text-xs">
                {{ t.process_key }} v{{ t.process_version }}
              </td>
              <td class="px-4 py-3 text-gray-600 dark:text-gray-300">
                {{ t.current_phase_label || '—' }}
              </td>
              <td class="px-4 py-3">
                <span class="text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
                      :class="STATUS_CLASS[t.status] || 'bg-gray-100 text-gray-500'">
                  {{ STATUS_LABEL[t.status] || t.status }}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                {{ formatDate(t.updated_at) }}
              </td>
            </tr>
            <tr v-if="!items.length && !loading">
              <td colspan="5" class="px-4 py-12 text-center text-sm text-gray-400 italic">
                Keine Aufträge gefunden
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between text-sm text-gray-400 mt-3">
        <span>{{ total }} Aufträge · Seite {{ page }} von {{ totalPages }}</span>
        <div class="flex gap-2">
          <button @click="offset = Math.max(0, offset - pageSize)" :disabled="offset === 0"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">← Zurück</button>
          <button @click="offset = offset + pageSize" :disabled="page >= totalPages"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">Weiter →</button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
