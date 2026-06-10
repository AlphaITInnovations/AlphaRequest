<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
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
  assignee_group_id?: string | null
  assignee_group_name?: string | null
}
interface DepartmentTicket {
  id: number; title: string; type_key: string; created_at: string
  status: string; priority: string
}
interface DepartmentGroup {
  group_id: string; group_name: string; tickets: DepartmentTicket[]
}
interface DashboardData {
  orders: DashboardTicket[]
  group_orders: DashboardTicket[]
  created_orders: DashboardTicket[]
  department_requests: DepartmentGroup[]
  allowed_ticket_types: string[]
}

// Vereinheitlichter Eintrag für den „Meine Abteilung"-Tab
interface DeptItem {
  id: number; title: string; type_key: string
  status: string; priority: string; created_at: string
  kind: 'assignment' | 'review'
  link: string
}
interface DeptGroup { group_id: string; group_name: string; tickets: DeptItem[] }

// ── State ─────────────────────────────────────────────────────────────────────
const loading   = ref(true)
const data      = ref<DashboardData>({ orders: [], group_orders: [], created_orders: [], department_requests: [], allowed_ticket_types: [] })

// ── Tabs ──────────────────────────────────────────────────────────────────────
type Tab = 'mine' | 'group' | 'created'
const activeTab = ref<Tab>('mine')

// ── Filter ────────────────────────────────────────────────────────────────────
const filter = ref({ search: '', status: 'all', priority: 'all' })

// ── Labels ────────────────────────────────────────────────────────────────────
const ticketTypes = [
  { key: 'hardware',                 label: 'Hardwarebestellung' },
  { key: 'zugang-beantragen',        label: 'Onboarding Mitarbeiter:innen' },
  { key: 'zugang-sperren',           label: 'Offboarding Mitarbeiter:innen' },
  { key: 'niederlassung-anmelden',   label: 'Niederlassung anmelden' },
  { key: 'niederlassung-umzug',      label: 'Niederlassung umziehen' },
  { key: 'niederlassung-schliessen', label: 'Niederlassung schließen' },
  { key: 'marketing-stellenanzeige', label: 'Marketing - Stellenanzeige' },
  { key: 'hotelbuchung',             label: 'Hotelbuchung' },
  { key: 'basis-ticket',             label: 'Ticket' },
]
const TYPE_LABEL: Record<string, string> = Object.fromEntries(ticketTypes.map(t => [t.key, t.label]))

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
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

function dotClass(s: string) {
  return { in_progress: 'bg-amber-400', in_request: 'bg-[#3EAAB8]', archived: 'bg-green-500', rejected: 'bg-red-500' }[s] ?? 'bg-gray-300'
}

// ── Counts ────────────────────────────────────────────────────────────────────
const mineCount    = computed(() => data.value.orders.filter(o => o.status !== 'archived' && o.status !== 'rejected').length)
const groupCount   = computed(() => baseDeptGroups.value.reduce((s, g) =>
  s + g.tickets.filter(t => t.status !== 'archived' && t.status !== 'rejected').length, 0))
const createdCount = computed(() => data.value.created_orders.filter(o => o.status !== 'archived').length)
const totalOpen    = computed(() => mineCount.value + groupCount.value)

// ── Filtering ─────────────────────────────────────────────────────────────────
function applyFilter<T extends { title: string; type_key: string; status: string; priority: string }>(list: T[]): T[] {
  return list.filter(o => {
    const q = filter.value.search.toLowerCase()
    return (
      (!q || o.title.toLowerCase().includes(q) || (TYPE_LABEL[o.type_key] ?? '').toLowerCase().includes(q)) &&
      (filter.value.status === 'all' || o.status === filter.value.status) &&
      (filter.value.priority === 'all' || o.priority === filter.value.priority)
    )
  })
}

const filteredMine    = computed(() => applyFilter(data.value.orders))
const openGroupDepts = ref<Record<string, boolean>>({})
const filteredCreated = computed(() => applyFilter(data.value.created_orders))
const filteredCreatedActive   = computed(() => filteredCreated.value.filter(o => o.status !== 'archived'))
const filteredCreatedArchived = computed(() => filteredCreated.value.filter(o => o.status === 'archived'))
const showArchived = ref(false)

// ── „Meine Abteilung" – vereinheitlicht ─────────────────────────────────────────
// Kombiniert zwei Quellen, gruppiert nach Abteilung (group_id):
//   • department_requests → Durchführungs-/Freigabe-Tickets (Phase „Durchführung").
//     group_id ist hier der KORREKTE Workflow-Department-Key → ?department=<id>.
//   • group_orders        → Tickets, die meiner Abteilung zur Bearbeitung
//     (Assignment-Phase) zugewiesen sind → Formular ohne department.
// Dedupe pro Abteilung über die Ticket-ID (Review hat Vorrang vor Assignment).
const baseDeptGroups = computed<DeptGroup[]>(() => {
  const map = new Map<string, DeptGroup & { seen: Set<number> }>()
  const ensure = (gid: string, name: string) => {
    if (!map.has(gid)) map.set(gid, { group_id: gid, group_name: name || 'Unbekannt', tickets: [], seen: new Set() })
    const e = map.get(gid)!
    if ((!e.group_name || e.group_name === 'Unbekannt') && name) e.group_name = name
    return e
  }

  // 1) Durchführung / Freigabe (autoritative Department-ID)
  for (const d of data.value.department_requests) {
    const g = ensure(d.group_id, d.group_name)
    for (const t of d.tickets) {
      g.tickets.push({
        id: t.id, title: t.title, type_key: t.type_key,
        status: t.status, priority: t.priority, created_at: t.created_at,
        kind: 'review',
        link: `/tickets/view/${t.type_key}/${t.id}?department=${d.group_id}`,
      })
      g.seen.add(t.id)
    }
  }

  // 2) Meiner Abteilung zur Bearbeitung zugewiesen (Assignment-Phase)
  for (const o of data.value.group_orders) {
    const gid = o.assignee_group_id || o.assignee_group_name || 'unknown'
    const g = ensure(gid, o.assignee_group_name || '')
    if (g.seen.has(o.id)) continue
    g.seen.add(o.id)
    g.tickets.push({
      id: o.id, title: o.title, type_key: o.type_key,
      status: o.status, priority: o.priority, created_at: o.created_at,
      kind: 'assignment',
      link: `/tickets/view/${o.type_key}/${o.id}`,
    })
  }

  return Array.from(map.values()).map(({ seen, ...g }) => g)
})

const myDepartmentGroups = computed<DeptGroup[]>(() =>
  baseDeptGroups.value
    .map(g => ({ ...g, tickets: applyFilter(g.tickets) }))
    .filter(g => g.tickets.length > 0)
)

const currentCount = computed(() => {
  if (activeTab.value === 'mine') return filteredMine.value.length
  if (activeTab.value === 'group') return myDepartmentGroups.value.reduce((s, g) => s + g.tickets.length, 0)
  return filteredCreated.value.length
})

// ── Actions ───────────────────────────────────────────────────────────────────
function openTicket(o: DashboardTicket) { router.push(`/tickets/view/${o.type_key}/${o.id}`) }
function openCreatedTicket(o: DashboardTicket) { router.push(`/tickets/overview/${o.id}`) }
function openDeptItem(t: DeptItem) { router.push(t.link) }
function toggleGroupDept(id: string) { openGroupDepts.value[id] = !openGroupDepts.value[id] }

// ── Init ──────────────────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const res = await client.get<{ data: DashboardData }>('/dashboard')
    data.value = res.data.data
    // Auto-open department accordions
    for (const g of baseDeptGroups.value) openGroupDepts.value[g.group_id] = true
    // Auto-select tab with most relevant content
    if (mineCount.value > 0) activeTab.value = 'mine'
    else if (groupCount.value > 0) activeTab.value = 'group'
    else if (createdCount.value > 0) activeTab.value = 'created'
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
          <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            <template v-if="totalOpen > 0">Du hast <strong class="text-gray-700 dark:text-gray-200">{{ totalOpen }}</strong> offene Aufgaben.</template>
            <template v-else>Alles erledigt – keine offenen Aufgaben.</template>
          </p>
        </div>
        <button @click="router.push('/tickets/new')"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl
                       bg-[#3EAAB8] hover:bg-[#2B7D89] text-white text-sm font-semibold
                       shadow-sm hover:shadow-md transition-all">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
          </svg>
          Neues Prozess-Ticket
        </button>
      </div>

      <!-- ── Stat Cards ── -->
      <div class="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <button @click="activeTab = 'mine'" class="stat" :class="activeTab === 'mine' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
            </span>
            <span class="text-2xl font-bold text-gray-900 dark:text-white">{{ mineCount }}</span>
          </div>
          <p class="stat-label">Mir zugewiesen</p>
        </button>

        <button @click="activeTab = 'group'" class="stat" :class="activeTab === 'group' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
            </span>
            <span class="text-2xl font-bold text-gray-900 dark:text-white">{{ groupCount }}</span>
          </div>
          <p class="stat-label">Meiner Abteilung</p>
        </button>

        <button @click="activeTab = 'created'" class="stat" :class="activeTab === 'created' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
            </span>
            <span class="text-2xl font-bold text-gray-900 dark:text-white">{{ createdCount }}</span>
          </div>
          <p class="stat-label">Von mir erstellt</p>
        </button>
      </div>

      <!-- ── Main Content ── -->
      <div class="space-y-0">

        <!-- Filter Bar -->
        <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-t-2xl overflow-hidden">

          <!-- Filter -->
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

          <!-- Result count -->
          <div class="px-5 py-2 text-xs text-gray-400 border-b border-gray-100 dark:border-white/[0.04]">
            {{ currentCount }} {{ currentCount === 1 ? 'Ergebnis' : 'Ergebnisse' }}
          </div>

          <!-- ═══ TAB: Mir zugewiesen ═══ -->
          <ul v-if="activeTab === 'mine'" class="divide-y divide-gray-100 dark:divide-white/[0.06] max-h-[560px] overflow-auto">
            <li v-for="o in filteredMine" :key="o.id" @click="openTicket(o)" class="row group">
              <div class="flex items-center gap-3.5 min-w-0">
                <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(o.status)" />
                <div class="min-w-0">
                  <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                  <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                </div>
              </div>
              <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[o.priority]">{{ PRIORITY_LABEL[o.priority] }}</span>
                <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[o.status]">{{ STATUS_LABEL[o.status] }}</span>
                <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </div>
            </li>
            <li v-if="filteredMine.length === 0" class="empty">Keine dir zugewiesenen Aufträge.</li>
          </ul>

          <!-- ═══ TAB: Meine Abteilung ═══ -->
          <div v-if="activeTab === 'group'" class="max-h-[560px] overflow-auto">
            <div class="divide-y divide-gray-100 dark:divide-white/[0.04]">
              <div v-for="g in myDepartmentGroups" :key="g.group_id">
                <button @click="toggleGroupDept(g.group_id)"
                        class="w-full flex items-center justify-between px-5 py-4
                               hover:bg-white/60 dark:hover:bg-[#263040] transition text-left">
                  <div class="flex items-center gap-2.5">
                    <span class="w-6 h-6 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400
                                 flex items-center justify-center flex-shrink-0">
                      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                      </svg>
                    </span>
                    <span class="text-sm font-medium text-gray-900 dark:text-white">{{ g.group_name }}</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">{{ g.tickets.length }}</span>
                    <svg class="w-4 h-4 text-gray-400 transition-transform duration-200"
                         :class="openGroupDepts[g.group_id] ? 'rotate-180' : ''"
                         viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                  </div>
                </button>
                <div v-show="openGroupDepts[g.group_id]" class="px-5 pb-4 space-y-2">
                  <div v-for="t in g.tickets" :key="t.kind + '-' + t.id" @click="openDeptItem(t)"
                       class="flex items-center justify-between px-4 py-3 rounded-xl cursor-pointer
                              bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                              hover:border-[#3EAAB8]/40 hover:shadow-sm transition group">
                    <div class="flex items-center gap-3 min-w-0">
                      <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(t.status)" />
                      <div class="min-w-0">
                        <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ t.title }}</p>
                        <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[t.type_key] ?? t.type_key }} · {{ t.created_at }}</p>
                      </div>
                    </div>
                    <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                      <span v-if="t.kind === 'review'"
                            class="hidden sm:inline text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8]">
                        Durchführung
                      </span>
                      <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[t.priority]">{{ PRIORITY_LABEL[t.priority] }}</span>
                      <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[t.status]">{{ STATUS_LABEL[t.status] }}</span>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <p v-if="myDepartmentGroups.length === 0" class="empty">Keine Aufträge für deine Abteilung.</p>
          </div>

          <!-- ═══ TAB: Erstellt ═══ -->
          <div v-if="activeTab === 'created'" class="max-h-[560px] overflow-auto">
            <ul class="divide-y divide-gray-100 dark:divide-white/[0.06]">
              <li v-for="o in filteredCreatedActive" :key="o.id" @click="openCreatedTicket(o)" class="row group">
                <div class="flex items-center gap-3.5 min-w-0">
                  <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(o.status)" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                    <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                  </div>
                </div>
                <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                  <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[o.priority]">{{ PRIORITY_LABEL[o.priority] }}</span>
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[o.status]">{{ STATUS_LABEL[o.status] }}</span>
                  <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </li>
              <li v-if="filteredCreatedActive.length === 0 && filteredCreatedArchived.length === 0" class="empty">Keine erstellten Aufträge.</li>
              <li v-else-if="filteredCreatedActive.length === 0" class="px-5 py-8 text-center text-sm text-gray-400 italic">Keine offenen Aufträge.</li>
            </ul>

            <!-- Erledigt -->
            <div v-if="filteredCreatedArchived.length > 0" class="border-t border-gray-200/80 dark:border-white/[0.09]">
              <button @click="showArchived = !showArchived"
                      class="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/60 dark:hover:bg-[#263040] transition text-left">
                <span class="text-sm font-medium text-gray-500 dark:text-gray-400">Erledigt</span>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">{{ filteredCreatedArchived.length }}</span>
                  <svg class="w-4 h-4 text-gray-400 transition-transform duration-200" :class="showArchived ? 'rotate-180' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                </div>
              </button>
              <ul v-show="showArchived" class="divide-y divide-gray-100 dark:divide-white/[0.06]">
                <li v-for="o in filteredCreatedArchived" :key="o.id" @click="openCreatedTicket(o)" class="row group opacity-60">
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

        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../style.css";

.stat {
  @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
         rounded-2xl p-4 text-left transition-all duration-150 hover:shadow-md hover:border-gray-300 dark:hover:border-white/20;
}
.stat-on { @apply ring-2 ring-[#3EAAB8]/40 border-[#3EAAB8]/30; }
.stat-icon { @apply w-8 h-8 rounded-lg flex items-center justify-center; }
.stat-label { @apply text-xs font-medium text-gray-500 dark:text-gray-400 mt-2; }

.fi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         placeholder-gray-400 px-3.5 py-2 text-sm
         focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}

.row {
  @apply flex items-center justify-between px-5 py-4 cursor-pointer
         hover:bg-white/60 dark:hover:bg-[#263040] transition;
}

.empty { @apply px-5 py-14 text-center text-sm text-gray-400 italic; }
</style>