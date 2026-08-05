<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'

interface Attachment {
  id: number
  ticket_id: number | null
  phase_key: string | null
  family_id: string
  version: number
  is_current: boolean
  original_filename: string
  content_type: string | null
  size_bytes: number
  size_human: string
  sha256: string | null
  uploaded_by_id: string | null
  uploaded_by_name: string | null
  uploaded_at: string | null
}

const router = useRouter()
const { showToast } = useToast()

const items   = ref<Attachment[]>([])
const total   = ref(0)
const loading = ref(false)
const expanded = ref<number | null>(null)

const stats = ref<{ count: number; total_bytes: number; total_human: string } | null>(null)

const fSearch  = ref('')
const pageSize = 25
const offset   = ref(0)

const page       = computed(() => Math.floor(offset.value / pageSize) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function downloadUrl(id: number) {
  return `/api/v1/attachments/${id}/download`
}

function formatDate(ts: string | null) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function openTicket(a: Attachment) {
  if (a.ticket_id) router.push(`/admin/tickets/${a.ticket_id}`)
}
function toggle(id: number) { expanded.value = expanded.value === id ? null : id }

// ── Laden ──────────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const { data } = await client.get('/settings/attachments/stats')
    stats.value = data.data
  } catch { /* nicht kritisch für die Liste */ }
}

let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  try {
    const { data } = await client.get('/settings/attachments', {
      params: { limit: pageSize, offset: offset.value, q: fSearch.value || undefined },
    })
    if (my !== reqId) return
    items.value = data.data.items
    total.value = data.data.total
  } finally {
    if (my === reqId) loading.value = false
  }
}

let debounce: ReturnType<typeof setTimeout> | null = null
watch(fSearch, () => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => { offset.value = 0; load() }, 250)
})
watch(offset, load)

function prev() { if (offset.value > 0) offset.value -= pageSize }
function next() { if (page.value < totalPages.value) offset.value += pageSize }

// ── Löschen ──────────────────────────────────────────────────────────────────
const deleting = ref<number | null>(null)
async function remove(a: Attachment) {
  if (!confirm(`Datei „${a.original_filename}“ wirklich löschen? Dies wird im Audit-Log festgehalten.`)) return
  deleting.value = a.id
  try {
    await client.delete(`/attachments/${a.id}`)
    showToast(`„${a.original_filename}“ gelöscht`)
    await Promise.all([load(), loadStats()])
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message || 'Löschen fehlgeschlagen', false)
  } finally {
    deleting.value = null
  }
}

onMounted(() => { loadStats(); load() })
onUnmounted(() => { if (debounce) clearTimeout(debounce) })
</script>

<template>
  <section>
    <h2 class="section-title mb-1">Dateien &amp; Anhänge</h2>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Übersicht aller hochgeladenen Dateien. Jeder Upload und jede Löschung ist im Audit-Log nachvollziehbar;
      neue Versionen einer Datei bleiben über die Historie erhalten.
    </div>

    <!-- Speicherplatz-Kacheln -->
    <div class="grid grid-cols-2 gap-3 mb-4 max-w-md">
      <div class="card-section !p-4">
        <div class="text-xs text-gray-400 uppercase tracking-wider mb-1">Dateien</div>
        <div class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{{ stats?.count ?? '—' }}</div>
      </div>
      <div class="card-section !p-4">
        <div class="text-xs text-gray-400 uppercase tracking-wider mb-1">Speicherplatz</div>
        <div class="text-2xl font-semibold text-gray-800 dark:text-gray-100">{{ stats?.total_human ?? '—' }}</div>
      </div>
    </div>

    <!-- Suche -->
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <input v-model="fSearch" placeholder="Suche (Dateiname, Person, Ticket-Nr.…)" class="afi flex-1 min-w-[14rem]" />
    </div>

    <div class="card-section !p-0 overflow-hidden">
      <div v-if="loading && items.length === 0" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-gray-400 uppercase tracking-wider border-b dark:border-white/[0.06]">
              <th class="px-4 py-3">Datei</th>
              <th class="px-4 py-3">Ticket</th>
              <th class="px-4 py-3">Hochgeladen von</th>
              <th class="px-4 py-3">Zeitpunkt</th>
              <th class="px-4 py-3 text-right">Größe</th>
              <th class="px-4 py-3 text-right">Aktion</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
            <template v-for="a in items" :key="a.id">
              <tr class="hover:bg-gray-50 dark:hover:bg-[#263040] transition align-top cursor-pointer"
                  @click="toggle(a.id)">
                <td class="px-4 py-3 text-gray-700 dark:text-gray-200 max-w-[20rem]">
                  <div class="flex items-center gap-2">
                    <span class="truncate">{{ a.original_filename }}</span>
                    <span v-if="a.version > 1"
                          class="text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400 whitespace-nowrap">
                      v{{ a.version }}
                    </span>
                  </div>
                </td>
                <td class="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-300">
                  <button v-if="a.ticket_id" @click.stop="openTicket(a)" class="text-[#3EAAB8] hover:underline">
                    🎫 #{{ a.ticket_id }}
                  </button>
                  <span v-else class="text-gray-400">—</span>
                </td>
                <td class="px-4 py-3 text-gray-600 dark:text-gray-300">{{ a.uploaded_by_name || '—' }}</td>
                <td class="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">{{ formatDate(a.uploaded_at) }}</td>
                <td class="px-4 py-3 whitespace-nowrap text-right text-gray-500 dark:text-gray-400">{{ a.size_human }}</td>
                <td class="px-4 py-3 whitespace-nowrap text-right">
                  <div class="flex items-center justify-end gap-2">
                    <a :href="downloadUrl(a.id)" @click.stop
                       class="text-[#3EAAB8] hover:underline" title="Herunterladen">⬇</a>
                    <button @click.stop="remove(a)" :disabled="deleting === a.id"
                            class="text-red-500 hover:text-red-600 disabled:opacity-40" title="Löschen">🗑</button>
                  </div>
                </td>
              </tr>
              <tr v-if="expanded === a.id" class="bg-gray-50 dark:bg-[#1A2130]">
                <td colspan="6" class="px-4 py-3">
                  <div class="text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                    <div><span class="font-mono">#{{ a.id }}</span> · Familie <span class="font-mono">{{ a.family_id }}</span> · Version {{ a.version }}{{ a.is_current ? ' (aktuell)' : '' }}</div>
                    <div v-if="a.phase_key">Phase: <span class="font-mono">{{ a.phase_key }}</span></div>
                    <div v-if="a.content_type">Typ: <span class="font-mono">{{ a.content_type }}</span></div>
                    <div v-if="a.sha256">SHA-256: <span class="font-mono break-all">{{ a.sha256 }}</span></div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="items.length === 0 && !loading">
              <td colspan="6" class="px-4 py-12 text-center text-sm text-gray-400 italic">Keine Dateien gefunden</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="flex items-center justify-between text-sm text-gray-400 mt-3">
      <span>{{ total }} Dateien · Seite {{ page }} von {{ totalPages }}</span>
      <div class="flex gap-2">
        <button @click="prev" :disabled="offset === 0"
                class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                       hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">← Zurück</button>
        <button @click="next" :disabled="page >= totalPages"
                class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                       hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">Weiter →</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
@reference "../../style.css";
.afi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
