<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'

const router = useRouter()
const auth   = useAuthStore()

interface DashboardTicket {
  id: number; title: string; type_key: string
  status: string; priority: string; created_at: string
}
interface DepartmentTicket {
  id: number; title: string; type_key: string; created_at: string
}
interface DepartmentGroup {
  group_id: string; group_name: string; tickets: DepartmentTicket[]
}
interface DashboardData {
  orders: DashboardTicket[]
  department_requests: DepartmentGroup[]
  allowed_ticket_types: string[]
}

const loading = ref(true)
const data    = ref<DashboardData>({ orders: [], department_requests: [], allowed_ticket_types: [] })
const filter  = ref({ search: '', status: 'all', priority: 'all', department: 'all' })
const openDepts = ref<Record<string, boolean>>({})

const ticketTypes = [
  { key: 'hardware',                 icon: '📦', label: 'Hardwarebestellung' },
  { key: 'zugang-beantragen',        icon: '🔑', label: 'Onboarding Mitarbeiter:innen' },
  { key: 'zugang-sperren',           icon: '🔒', label: 'Offboarding Mitarbeiter:innen' },
  { key: 'niederlassung-anmelden',   icon: '🏢', label: 'Niederlassung anmelden' },
  { key: 'niederlassung-umzug',      icon: '🔄', label: 'Niederlassung umziehen' },
  { key: 'niederlassung-schliessen', icon: '❌', label: 'Niederlassung schließen' },
  { key: 'marketing-stellenanzeige', icon: '📄', label: 'Stellenanzeige' },
]

// Erlaubte Typen aus der Backend-Antwort – konsistent mit can_user_create_ticket serverseitig
const allowedTypes = computed(() =>
  ticketTypes.filter(t => data.value.allowed_ticket_types.includes(t.key))
)

const filteredOrders = computed(() =>
  data.value.orders.filter(o => {
    const q = filter.value.search.toLowerCase()
    return (
      (!q || o.title.toLowerCase().includes(q) || o.type_key.toLowerCase().includes(q)) &&
      (filter.value.status   === 'all' || o.status   === filter.value.status) &&
      (filter.value.priority === 'all' || o.priority === filter.value.priority)
    )
  })
)

const filteredDepts = computed(() =>
  filter.value.department === 'all'
    ? data.value.department_requests
    : data.value.department_requests.filter(d => d.group_id === filter.value.department)
)

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-100  text-amber-700  dark:bg-amber-900/30  dark:text-amber-400',
  in_request:  'bg-[#3EAAB8]/10 text-[#3EAAB8] dark:bg-[#3EAAB8]/20',
  archived:    'bg-green-100  text-green-700  dark:bg-green-900/30  dark:text-green-400',
  rejected:    'bg-red-100    text-red-700    dark:bg-red-900/30    dark:text-red-400',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}
const PRIORITY_CLASS: Record<string, string> = {
  low:      'text-gray-400',
  medium:   'text-blue-400',
  high:     'text-amber-500',
  critical: 'text-red-500',
}

function openTicket(o: DashboardTicket) {
  router.push(`/tickets/edit/${o.type_key}/${o.id}`)
}
function openGroupTicket(t: DepartmentTicket, groupId: string) {
  router.push(`/tickets/group/${t.type_key}/${t.id}?department=${groupId}`)
}
function openNew(key: string) {
  router.push(`/tickets/new/${key}`)
}
function toggleDept(id: string) {
  openDepts.value[id] = !openDepts.value[id]
}

onMounted(async () => {
  try {
    const res = await client.get<{ data: DashboardData }>('/dashboard')
    data.value = res.data.data
    data.value.department_requests.forEach(d => { openDepts.value[d.group_id] = true })
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout title="Übersicht">

    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else class="space-y-8">

      <div>
        <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
          Willkommen zurück,
          <span class="text-[#3EAAB8]">{{ auth.user?.displayName }}</span> 👋
        </h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">
          Hier ist deine aktuelle Übersicht.
        </p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">

        <!-- ── Neuer Auftrag ── -->
        <aside class="space-y-3 h-fit lg:sticky lg:top-4">
          <h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 px-1">
            Neuer Auftrag
          </h2>
          <div class="space-y-2">
            <button
              v-for="t in allowedTypes" :key="t.key"
              @click="openNew(t.key)"
              class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left
                     bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                     transition-all duration-150 shadow-sm hover:shadow-md"
            >
              <span class="text-base leading-none">{{ t.icon }}</span>
              <span class="text-sm font-medium truncate">{{ t.label }}</span>
            </button>
            <p v-if="allowedTypes.length === 0"
               class="text-sm text-gray-400 italic px-1">
              Keine Auftragstypen verfügbar.
            </p>
          </div>
        </aside>

        <!-- ── Content ── -->
        <section class="space-y-6 min-w-0">

          <!-- Deine Aufträge -->
          <div class="rounded-2xl border border-gray-200/80 dark:border-white/[0.09]
                      bg-gray-50 dark:bg-[#1A2130] overflow-hidden">
            <div class="px-6 py-4 border-b border-gray-200/80 dark:border-white/[0.09]
                        flex justify-between items-center">
              <h2 class="text-base font-semibold text-gray-900 dark:text-white">Deine Aufträge</h2>
              <span class="text-xs text-gray-400 bg-gray-100 dark:bg-white/[0.07]
                           px-2.5 py-1 rounded-full font-medium">
                {{ filteredOrders.length }}
              </span>
            </div>

            <div class="px-6 py-4 border-b border-gray-200/80 dark:border-white/[0.09]
                        grid grid-cols-1 md:grid-cols-3 gap-3">
              <input v-model="filter.search" placeholder="Suchen…"
                     class="w-full rounded-xl border border-gray-200 dark:border-white/10
                            bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                            placeholder-gray-400 px-3.5 py-2 text-sm
                            focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition" />
              <select v-model="filter.status"
                      class="w-full rounded-xl border border-gray-200 dark:border-white/10
                             bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                             px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition">
                <option value="all">Alle Status</option>
                <option value="in_request">Zu bearbeiten</option>
                <option value="in_progress">In Bearbeitung</option>
                <option value="archived">Erledigt</option>
                <option value="rejected">Abgelehnt</option>
              </select>
              <select v-model="filter.priority"
                      class="w-full rounded-xl border border-gray-200 dark:border-white/10
                             bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                             px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition">
                <option value="all">Alle Prioritäten</option>
                <option value="low">Niedrig</option>
                <option value="medium">Mittel</option>
                <option value="high">Hoch</option>
                <option value="critical">Kritisch</option>
              </select>
            </div>

            <ul class="divide-y divide-gray-100 dark:divide-white/[0.06] max-h-[460px] overflow-auto">
              <li v-for="o in filteredOrders" :key="o.id"
                  @click="openTicket(o)"
                  class="flex items-center justify-between px-6 py-5 cursor-pointer
                         hover:bg-gray-50 dark:hover:bg-[#263040] transition group">
                <div class="flex items-center gap-4 min-w-0">
                  <div class="w-2 h-2 rounded-full flex-shrink-0"
                       :class="{
                         'bg-amber-400': o.status === 'in_progress',
                         'bg-[#3EAAB8]': o.status === 'in_request',
                         'bg-green-500': o.status === 'archived',
                         'bg-red-500':   o.status === 'rejected',
                         'bg-gray-300':  !['in_progress','in_request','archived','rejected'].includes(o.status),
                       }" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate
                               group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                    <p class="text-xs text-gray-400 mt-0.5">{{ o.created_at }}</p>
                  </div>
                </div>
                <div class="flex items-center gap-3 flex-shrink-0 ml-4">
                  <span class="text-xs font-medium" :class="PRIORITY_CLASS[o.priority] ?? 'text-gray-400'">
                    {{ PRIORITY_LABEL[o.priority] ?? o.priority }}
                  </span>
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full"
                        :class="STATUS_CLASS[o.status] ?? 'bg-gray-100 text-gray-500'">
                    {{ STATUS_LABEL[o.status] ?? o.status }}
                  </span>
                  <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors"
                       viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="9 18 15 12 9 6"/>
                  </svg>
                </div>
              </li>
              <li v-if="filteredOrders.length === 0"
                  class="px-6 py-12 text-center text-sm text-gray-400 italic">
                Keine Aufträge gefunden.
              </li>
            </ul>
          </div>

          <!-- Fachabteilungen -->
          <div v-if="data.department_requests.length > 0"
               class="rounded-2xl border border-gray-200/80 dark:border-white/[0.09]
                      bg-gray-50 dark:bg-[#1A2130] overflow-hidden">
            <div class="px-6 py-4 border-b border-gray-200/80 dark:border-white/[0.09]
                        flex items-center justify-between">
              <h2 class="text-base font-semibold text-gray-900 dark:text-white">
                Fachabteilungen · Deine Aufgaben
              </h2>
              <select v-model="filter.department"
                      class="rounded-xl border border-gray-200 dark:border-white/10
                             bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                             px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition">
                <option value="all">Alle</option>
                <option v-for="d in data.department_requests" :key="d.group_id" :value="d.group_id">
                  {{ d.group_name }}
                </option>
              </select>
            </div>

            <div class="divide-y divide-gray-100 dark:divide-white/[0.04]">
              <div v-for="dept in filteredDepts" :key="dept.group_id">
                <button @click="toggleDept(dept.group_id)"
                        class="w-full flex items-center justify-between px-6 py-4
                               hover:bg-gray-50 dark:hover:bg-[#263040] transition text-left">
                  <span class="text-sm font-medium text-gray-900 dark:text-white">{{ dept.group_name }}</span>
                  <div class="flex items-center gap-2.5">
                    <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8]">
                      {{ dept.tickets.length }}
                    </span>
                    <svg class="w-4 h-4 text-gray-400 transition-transform duration-200"
                         :class="openDepts[dept.group_id] ? 'rotate-180' : ''"
                         viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                  </div>
                </button>
                <div v-show="openDepts[dept.group_id]" class="px-6 pb-4 space-y-2">
                  <div v-for="t in dept.tickets" :key="t.id"
                       @click="openGroupTicket(t, dept.group_id)"
                       class="flex items-center justify-between px-4 py-3 rounded-xl cursor-pointer
                              bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                              hover:border-[#3EAAB8]/40 hover:shadow-sm transition group">
                    <div class="min-w-0">
                      <p class="text-sm font-medium text-gray-900 dark:text-white truncate
                                 group-hover:text-[#3EAAB8] transition-colors">{{ t.title }}</p>
                      <p class="text-xs text-gray-400 mt-0.5">{{ t.type_key }} · {{ t.created_at }}</p>
                    </div>
                    <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 flex-shrink-0 ml-3
                                group-hover:text-[#3EAAB8] transition-colors"
                         viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="9 18 15 12 9 6"/>
                    </svg>
                  </div>
                  <p v-if="dept.tickets.length === 0" class="text-sm text-gray-400 italic px-1 py-2">
                    Keine offenen Aufgaben.
                  </p>
                </div>
              </div>
            </div>
          </div>

        </section>
      </div>
    </div>
  </AppLayout>
</template>