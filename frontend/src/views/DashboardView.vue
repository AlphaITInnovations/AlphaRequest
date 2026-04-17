<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'

const router = useRouter()
const auth   = useAuthStore()

// ── Types ─────────────────────────────────────────────────────────────────────
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
  created_orders: DashboardTicket[]
  department_requests: DepartmentGroup[]
  allowed_ticket_types: string[]
}

// ── State ─────────────────────────────────────────────────────────────────────
const loading   = ref(true)
const data      = ref<DashboardData>({ orders: [], created_orders: [], department_requests: [], allowed_ticket_types: [] })
const openDepts = ref<Record<string, boolean>>({})

// ── Tabs ──────────────────────────────────────────────────────────────────────
type Tab = 'assigned' | 'created' | 'departments'
const activeTab = ref<Tab>('assigned')

// ── Filter (persistent across tabs) ───────────────────────────────────────────
const filter = ref({ search: '', status: 'all', priority: 'all', department: 'all' })

// ── Ticket type config ────────────────────────────────────────────────────────
const ticketTypes = [
  { key: 'hardware',                 icon: '📦', label: 'Hardwarebestellung' },
  { key: 'zugang-beantragen',        icon: '🔑', label: 'Onboarding Mitarbeiter:innen' },
  { key: 'zugang-sperren',           icon: '🔒', label: 'Offboarding Mitarbeiter:innen' },
  { key: 'niederlassung-anmelden',   icon: '🏢', label: 'Niederlassung anmelden' },
  { key: 'niederlassung-umzug',      icon: '🔄', label: 'Niederlassung umziehen' },
  { key: 'niederlassung-schliessen', icon: '❌', label: 'Niederlassung schließen' },
  { key: 'marketing-stellenanzeige', icon: '📄', label: 'Marketing - Stellenanzeige' },
]
const TYPE_LABEL: Record<string, string> = Object.fromEntries(ticketTypes.map(t => [t.key, t.label]))

const allowedTypes = computed(() =>
  ticketTypes.filter(t => data.value.allowed_ticket_types.includes(t.key))
)

// ── Labels & styles ───────────────────────────────────────────────────────────
const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'In Durchführung',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  in_request:  'bg-[#3EAAB8]/10 text-[#3EAAB8] dark:bg-[#3EAAB8]/20',
  archived:    'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}
const PRIORITY_CLASS: Record<string, string> = {
  low: 'text-gray-400', medium: 'text-blue-400', high: 'text-amber-500', critical: 'text-red-500',
}

function dotClass(status: string): string {
  return { in_progress: 'bg-amber-400', in_request: 'bg-[#3EAAB8]', archived: 'bg-green-500', rejected: 'bg-red-500' }[status] ?? 'bg-gray-300'
}

// ── Stat counts ───────────────────────────────────────────────────────────────
const assignedOpen   = computed(() => data.value.orders.filter(o => o.status !== 'archived' && o.status !== 'rejected').length)
const createdOpen    = computed(() => data.value.created_orders.filter(o => o.status !== 'archived').length)
const deptTotal      = computed(() => data.value.department_requests.reduce((s, d) => s + d.tickets.length, 0))

// ── Filtered lists ────────────────────────────────────────────────────────────
function applyFilter(list: DashboardTicket[]) {
  return list.filter(o => {
    const q = filter.value.search.toLowerCase()
    return (
      (!q || o.title.toLowerCase().includes(q) || o.type_key.toLowerCase().includes(q) || (TYPE_LABEL[o.type_key] ?? '').toLowerCase().includes(q)) &&
      (filter.value.status === 'all' || o.status === filter.value.status) &&
      (filter.value.priority === 'all' || o.priority === filter.value.priority)
    )
  })
}

const filteredAssigned = computed(() => applyFilter(data.value.orders))
const filteredCreated  = computed(() => applyFilter(data.value.created_orders))
const filteredCreatedActive   = computed(() => filteredCreated.value.filter(o => o.status !== 'archived'))
const filteredCreatedArchived = computed(() => filteredCreated.value.filter(o => o.status === 'archived'))
const showArchivedCreated = ref(false)
const filteredDepts    = computed(() =>
  filter.value.department === 'all'
    ? data.value.department_requests
    : data.value.department_requests.filter(d => d.group_id === filter.value.department)
)

// Current tab count (for the result indicator)
const currentCount = computed(() => {
  if (activeTab.value === 'assigned') return filteredAssigned.value.length
  if (activeTab.value === 'created') return filteredCreated.value.length
  return filteredDepts.value.reduce((s, d) => s + d.tickets.length, 0)
})

// ── Actions ───────────────────────────────────────────────────────────────────
function openTicket(o: DashboardTicket) {
  router.push(`/tickets/edit/${o.type_key}/${o.id}`)
}
function openCreatedTicket(o: DashboardTicket) {
  if (o.status === 'in_progress') router.push(`/tickets/edit/${o.type_key}/${o.id}`)
  else router.push(`/tickets/overview/${o.id}`)
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

// ── Init ──────────────────────────────────────────────────────────────────────
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

    <div v-else class="space-y-6">

      <!-- ── Header ── -->
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
            Willkommen zurück,
            <span class="text-[#3EAAB8]">{{ auth.user?.displayName }}</span> 👋
          </h1>
          <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">Hier ist deine aktuelle Übersicht.</p>
        </div>
      </div>

      <!-- ── Stat Cards ── REMOVED -->

      <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">

        <!-- ══════════════════════════════════════════
             SIDEBAR: Neuer Auftrag (LINKS)
        ══════════════════════════════════════════ -->
        <aside class="space-y-3 h-fit lg:sticky lg:top-4">
          <h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 px-1">
            Neuer Auftrag
          </h2>
          <div class="space-y-2">
            <button v-for="t in allowedTypes" :key="t.key" @click="openNew(t.key)"
                    class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left
                           bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                           transition-all duration-150 shadow-sm hover:shadow-md">
              <span class="text-base leading-none">{{ t.icon }}</span>
              <span class="text-sm font-medium truncate">{{ t.label }}</span>
            </button>
            <p v-if="allowedTypes.length === 0" class="text-sm text-gray-400 italic px-1">
              Keine Auftragstypen verfügbar.
            </p>
          </div>
        </aside>

        <!-- ══════════════════════════════════════════
             MAIN CONTENT (RECHTS)
        ══════════════════════════════════════════ -->
        <div class="min-w-0 space-y-0">

          <!-- Tab Bar + Filter -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-t-2xl overflow-hidden">

            <!-- Tabs -->
            <div class="flex items-center border-b border-gray-200/80 dark:border-white/[0.09]">
              <button @click="activeTab = 'assigned'" class="tab-btn" :class="activeTab === 'assigned' ? 'tab-active' : 'tab-idle'">
                Meine Aufträge
                <span v-if="assignedOpen > 0" class="badge" :class="activeTab === 'assigned' ? 'badge-on' : 'badge-off'">{{ assignedOpen }}</span>
              </button>
              <button @click="activeTab = 'created'" class="tab-btn" :class="activeTab === 'created' ? 'tab-active' : 'tab-idle'">
                Erstellt
                <span v-if="createdOpen > 0" class="badge" :class="activeTab === 'created' ? 'badge-on' : 'badge-off'">{{ createdOpen }}</span>
              </button>
              <button @click="activeTab = 'departments'" class="tab-btn" :class="activeTab === 'departments' ? 'tab-active' : 'tab-idle'">
                Fachabteilung
                <span v-if="deptTotal > 0" class="badge" :class="activeTab === 'departments' ? 'badge-on' : 'badge-off'">{{ deptTotal }}</span>
              </button>
            </div>

            <!-- Shared Filter Row -->
            <div class="px-5 py-3.5 grid grid-cols-1 sm:grid-cols-[1fr_auto_auto] gap-3 items-center">
              <div class="relative">
                <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
                </svg>
                <input v-model="filter.search" placeholder="Aufträge durchsuchen…" class="fi !pl-10" />
              </div>
              <select v-model="filter.status" class="fi">
                <option value="all">Alle Status</option>
                <option value="in_request">Zu bearbeiten</option>
                <option value="in_progress">In Bearbeitung</option>
                <option value="archived">Erledigt</option>
                <option value="rejected">Abgelehnt</option>
              </select>
              <select v-model="filter.priority" class="fi">
                <option value="all">Alle Prioritäten</option>
                <option value="low">Niedrig</option>
                <option value="medium">Mittel</option>
                <option value="high">Hoch</option>
                <option value="critical">Kritisch</option>
              </select>
            </div>
          </div>

          <!-- List Container -->
          <div class="bg-gray-50 dark:bg-[#1A2130] border border-t-0 border-gray-200/80 dark:border-white/[0.09]
                      rounded-b-2xl overflow-hidden">

            <!-- Department filter (only in dept tab) -->
            <div v-if="activeTab === 'departments' && data.department_requests.length > 1"
                 class="px-5 py-3 border-b border-gray-200/80 dark:border-white/[0.09] flex items-center justify-between">
              <span class="text-xs text-gray-400">Abteilung filtern</span>
              <select v-model="filter.department" class="fi w-auto text-xs py-1.5">
                <option value="all">Alle Abteilungen</option>
                <option v-for="d in data.department_requests" :key="d.group_id" :value="d.group_id">
                  {{ d.group_name }}
                </option>
              </select>
            </div>

            <!-- Result count -->
            <div class="px-5 py-2 text-xs text-gray-400 border-b border-gray-100 dark:border-white/[0.04]">
              {{ currentCount }} {{ currentCount === 1 ? 'Ergebnis' : 'Ergebnisse' }}
            </div>

            <!-- ═══ TAB: Assigned ═══ -->
            <ul v-if="activeTab === 'assigned'"
                class="divide-y divide-gray-100 dark:divide-white/[0.06] max-h-[540px] overflow-auto">
              <li v-for="o in filteredAssigned" :key="o.id" @click="openTicket(o)" class="ticket-row group">
                <div class="flex items-center gap-3.5 min-w-0">
                  <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(o.status)" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                    <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                  </div>
                </div>
                <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                  <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[o.priority]">{{ PRIORITY_LABEL[o.priority] ?? o.priority }}</span>
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[o.status] ?? 'bg-gray-100 text-gray-500'">{{ STATUS_LABEL[o.status] ?? o.status }}</span>
                  <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </li>
              <li v-if="filteredAssigned.length === 0" class="empty">Keine zugewiesenen Aufträge gefunden.</li>
            </ul>

            <!-- ═══ TAB: Created ═══ -->
            <div v-if="activeTab === 'created'" class="max-h-[540px] overflow-auto">
              <!-- Aktive Aufträge -->
              <ul class="divide-y divide-gray-100 dark:divide-white/[0.06]">
                <li v-for="o in filteredCreatedActive" :key="o.id" @click="openCreatedTicket(o)" class="ticket-row group">
                  <div class="flex items-center gap-3.5 min-w-0">
                    <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(o.status)" />
                    <div class="min-w-0">
                      <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                      <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                    </div>
                  </div>
                  <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                    <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[o.priority]">{{ PRIORITY_LABEL[o.priority] ?? o.priority }}</span>
                    <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[o.status] ?? 'bg-gray-100 text-gray-500'">{{ STATUS_LABEL[o.status] ?? o.status }}</span>
                    <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                  </div>
                </li>
                <li v-if="filteredCreatedActive.length === 0 && filteredCreatedArchived.length === 0" class="empty">
                  Keine erstellten Aufträge gefunden.
                </li>
                <li v-else-if="filteredCreatedActive.length === 0" class="px-5 py-8 text-center text-sm text-gray-400 italic">
                  Keine offenen Aufträge.
                </li>
              </ul>

              <!-- Erledigt (einklappbar) -->
              <div v-if="filteredCreatedArchived.length > 0"
                   class="border-t border-gray-200/80 dark:border-white/[0.09]">
                <button @click="showArchivedCreated = !showArchivedCreated"
                        class="w-full flex items-center justify-between px-5 py-3.5
                               hover:bg-white/60 dark:hover:bg-[#263040] transition text-left">
                  <span class="text-sm font-medium text-gray-500 dark:text-gray-400">Erledigt</span>
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold px-2.5 py-1 rounded-full
                                 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                      {{ filteredCreatedArchived.length }}
                    </span>
                    <svg class="w-4 h-4 text-gray-400 transition-transform duration-200"
                         :class="showArchivedCreated ? 'rotate-180' : ''"
                         viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                  </div>
                </button>
                <ul v-show="showArchivedCreated"
                    class="divide-y divide-gray-100 dark:divide-white/[0.06]">
                  <li v-for="o in filteredCreatedArchived" :key="o.id" @click="openCreatedTicket(o)" class="ticket-row group opacity-70">
                    <div class="flex items-center gap-3.5 min-w-0">
                      <div class="w-2 h-2 rounded-full flex-shrink-0 bg-green-500" />
                      <div class="min-w-0">
                        <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                        <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                      </div>
                    </div>
                    <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                      <span class="text-xs font-medium px-2.5 py-1 rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">Erledigt</span>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                  </li>
                </ul>
              </div>
            </div>

            <!-- ═══ TAB: Departments ═══ -->
            <div v-if="activeTab === 'departments'" class="max-h-[540px] overflow-auto">
              <div class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                <div v-for="dept in filteredDepts" :key="dept.group_id">
                  <button @click="toggleDept(dept.group_id)"
                          class="w-full flex items-center justify-between px-5 py-4
                                 hover:bg-white/60 dark:hover:bg-[#263040] transition text-left">
                    <span class="text-sm font-medium text-gray-900 dark:text-white">{{ dept.group_name }}</span>
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8]">{{ dept.tickets.length }}</span>
                      <svg class="w-4 h-4 text-gray-400 transition-transform duration-200"
                           :class="openDepts[dept.group_id] ? 'rotate-180' : ''"
                           viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </div>
                  </button>
                  <div v-show="openDepts[dept.group_id]" class="px-5 pb-4 space-y-2">
                    <div v-for="t in dept.tickets" :key="t.id"
                         @click="openGroupTicket(t, dept.group_id)"
                         class="flex items-center justify-between px-4 py-3 rounded-xl cursor-pointer
                                bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                                hover:border-[#3EAAB8]/40 hover:shadow-sm transition group">
                      <div class="min-w-0">
                        <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ t.title }}</p>
                        <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[t.type_key] ?? t.type_key }} · {{ t.created_at }}</p>
                      </div>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 flex-shrink-0 ml-3 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                    <p v-if="dept.tickets.length === 0" class="text-sm text-gray-400 italic px-1 py-2">Keine offenen Aufgaben.</p>
                  </div>
                </div>
              </div>
              <p v-if="filteredDepts.length === 0" class="empty">Keine Fachabteilungsaufgaben vorhanden.</p>
            </div>

          </div>
        </div>

      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../style.css";

/* ── Tabs ── */
.tab-btn {
  @apply relative flex items-center gap-2 px-5 py-3.5 text-sm font-medium transition-colors whitespace-nowrap;
}
.tab-active {
  @apply text-[#3EAAB8] border-b-2 border-[#3EAAB8];
}
.tab-idle {
  @apply text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200
         border-b-2 border-transparent;
}

/* ── Badges ── */
.badge {
  @apply text-xs font-semibold px-1.5 py-0.5 rounded-full min-w-[20px] text-center leading-tight;
}
.badge-on  { @apply bg-[#3EAAB8] text-white; }
.badge-off { @apply bg-gray-200 dark:bg-white/10 text-gray-500 dark:text-gray-400; }

/* ── Filter Input ── */
.fi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         placeholder-gray-400 px-3.5 py-2 text-sm
         focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}

/* ── Ticket Row ── */
.ticket-row {
  @apply flex items-center justify-between px-5 py-4 cursor-pointer
         hover:bg-white/60 dark:hover:bg-[#263040] transition;
}

/* ── Empty State ── */
.empty {
  @apply px-5 py-14 text-center text-sm text-gray-400 italic;
}
</style>