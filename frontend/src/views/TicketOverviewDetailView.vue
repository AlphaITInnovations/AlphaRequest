<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'

const route  = useRoute()
const router = useRouter()
const id     = Number(route.params.id)

const loading = ref(true)
const data    = ref<any>(null)

const STATUS_LABEL: Record<string, string> = {
  in_request: 'Zu bearbeiten', in_progress: 'In Bearbeitung',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const STATUS_CLASS: Record<string, string> = {
  in_request:  'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  in_progress: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  archived:    'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}
const DEPT_CLASS: Record<string, string> = {
  done:        'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  open:        'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  skipped:     'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
}
const ACTION_LABEL: Record<string, string> = {
  ticket_created:        '📝 Ticket erstellt',
  ticket_updated:        '✏️ Ticket bearbeitet',
  ticket_submitted:      '📤 An Fachabteilungen übergeben',
  department_done:       '✅ Fachabteilung erledigt',
  ticket_archived:       '📦 Ticket archiviert',
  ticket_archived_manual:'📦 Manuell archiviert',
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

function labelize(s: string) {
  return s.replace(/_/g, ' ').replace(/-/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

// Rekursiver JSON-Renderer
function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function isArray(v: unknown): v is unknown[] {
  return Array.isArray(v)
}


onMounted(async () => {
  try {
    const { data: res } = await client.get(`/overview/tickets/${id}`)
    data.value = res.data
  } catch {
    router.push('/tickets')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout title="Ticket-Übersicht">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-gray-400">Ticket #{{ data.id }}</p>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white mt-0.5">{{ data.title }}</h1>
        </div>
        <button @click="router.push('/tickets')"
                class="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/10
                       text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
          ← Zur Übersicht
        </button>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">

        <!-- ── Sidebar ── -->
        <aside class="space-y-4">

          <!-- Meta -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 space-y-3 text-sm">
            <h2 class="font-semibold text-gray-900 dark:text-white">Übersicht</h2>
            <div>
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Status</p>
              <span class="text-xs font-medium px-2.5 py-1 rounded-full"
                    :class="STATUS_CLASS[data.status] ?? 'bg-gray-100 text-gray-500'">
                {{ STATUS_LABEL[data.status] ?? data.status }}
              </span>
            </div>
            <div>
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Priorität</p>
              <p class="font-medium text-gray-900 dark:text-white capitalize">{{ data.priority }}</p>
            </div>
            <div>
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Erstellt</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ formatDate(data.created_at) }}</p>
            </div>
            <div v-if="data.updated_at">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Geändert</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ formatDate(data.updated_at) }}</p>
            </div>
          </div>

          <!-- Antragsteller -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Antragsteller</p>
            <p class="font-medium text-gray-900 dark:text-white">{{ data.owner_name }}</p>
            <div v-if="data.accountable_name" class="mt-3">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Verantwortlicher</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.accountable_name }}</p>
            </div>
            <div v-if="data.comment" class="mt-3">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Kommentar</p>
              <p class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ data.comment }}</p>
            </div>
          </div>

          <!-- Fachabteilungen -->
          <div v-if="Object.keys(data.departments).length > 0"
               class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <p class="font-semibold text-gray-900 dark:text-white mb-3">Fachabteilungen</p>
            <ul class="space-y-2">
              <li v-for="(dept, gid) in data.departments" :key="gid"
                  class="flex items-center justify-between">
                <span class="text-gray-700 dark:text-gray-300">{{ dept.name }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                      :class="DEPT_CLASS[dept.status] ?? 'bg-gray-100 text-gray-500'">
                  {{ dept.status }}
                </span>
              </li>
            </ul>
          </div>
        </aside>

        <!-- ── Content ── -->
        <section class="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-5 items-start">

          <!-- Auftragsinhalt -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-3">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">Auftragsinhalt</h2>

            <template v-if="data.description && Object.keys(data.description).length > 0">
              <details v-for="(section, key) in data.description" :key="key"
                       class="border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden">
                <summary class="cursor-pointer px-4 py-3 font-medium text-sm
                                text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/5">
                  {{ labelize(String(key)) }}
                </summary>
                <div class="p-4 border-t border-gray-100 dark:border-white/[0.04]">
                  <DescriptionRenderer :value="section" />
                </div>
              </details>
            </template>
            <p v-else class="text-sm text-gray-400 italic">Keine Auftragsdaten vorhanden.</p>
          </div>

          <!-- Verlauf -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 xl:sticky xl:top-4 max-h-[75vh] overflow-auto">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white mb-5">Verlauf</h2>

            <ol v-if="data.history.length > 0"
                class="relative border-l border-gray-200 dark:border-white/[0.09] pl-5 space-y-5">
              <li v-for="e in data.history" :key="e.timestamp"
                  class="relative">
                <span class="absolute -left-[17px] top-1 w-3 h-3 rounded-full bg-[#3EAAB8]"/>
                <div class="bg-gray-50 dark:bg-[#1A2130] rounded-xl p-3">
                  <div class="flex items-start justify-between gap-3">
                    <p class="text-sm font-medium text-gray-900 dark:text-white">
                      {{ ACTION_LABEL[e.action] ?? e.action }}
                      <span v-if="e.action === 'department_done' && e.details?.department_name">
                        – {{ e.details.department_name }}
                      </span>
                    </p>
                    <span class="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
                      {{ e.actor.name }}
                    </span>
                  </div>
                  <p class="text-xs text-gray-400 mt-1">{{ formatDate(e.timestamp) }}</p>
                </div>
              </li>
            </ol>
            <p v-else class="text-sm text-gray-400 italic">Kein Verlauf vorhanden.</p>
          </div>

        </section>
      </div>
    </div>
  </AppLayout>
</template>

<script lang="ts">
import { defineComponent, h } from 'vue'

// Rekursiver Renderer für beliebige JSON-Strukturen
const DescriptionRenderer = defineComponent({
  name: 'DescriptionRenderer',
  props: { value: { required: true } },
  setup(props) {
    function render(val: unknown): ReturnType<typeof h> {
      if (val === null || val === undefined || val === '') {
        return h('span', { class: 'text-gray-400' }, '—')
      }
      if (typeof val === 'boolean') {
        return h('span', {
          class: val
            ? 'px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 font-medium'
            : 'px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 font-medium'
        }, val ? 'Ja' : 'Nein')
      }
      if (Array.isArray(val)) {
        if (val.length === 0) return h('span', { class: 'text-gray-400' }, '—')
        return h('div', { class: 'space-y-2' },
          val.map((item, i) => h('div', {
            key: i,
            class: 'border border-gray-200 dark:border-white/[0.06] rounded-lg p-3'
          }, [render(item)]))
        )
      }
      if (typeof val === 'object') {
        const entries = Object.entries(val as Record<string, unknown>)
          .filter(([, v]) => v !== null && v !== undefined && v !== '')
        if (entries.length === 0) return h('span', { class: 'text-gray-400' }, '—')
        return h('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-3' },
          entries.map(([k, v]) => {
            const isComplex = typeof v === 'object' && v !== null
            return h('div', {
              key: k,
              class: isComplex
                ? 'md:col-span-2 border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden'
                : 'border border-gray-200 dark:border-white/[0.06] rounded-xl p-3'
            }, isComplex ? [
              h('div', { class: 'px-4 py-2 bg-gray-50 dark:bg-white/5 border-b border-gray-200 dark:border-white/[0.06] text-xs font-semibold text-gray-500 uppercase tracking-wider' },
                k.replace(/_/g, ' ')),
              h('div', { class: 'p-4' }, [render(v)])
            ] : [
              h('p', { class: 'text-xs text-gray-400 mb-1' }, k.replace(/_/g, ' ')),
              render(v)
            ])
          })
        )
      }
      const s = String(val)
      if (s.length > 80 || s.includes('\n')) {
        return h('pre', { class: 'text-sm whitespace-pre-wrap text-gray-800 dark:text-gray-200' }, s)
      }
      return h('span', { class: 'text-sm font-medium text-gray-900 dark:text-white' }, s)
    }
    return () => render(props.value)
  }
})
</script>