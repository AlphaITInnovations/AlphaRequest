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
// Einheitlicher „Meine Abteilung"-Eintrag (vom Backend fertig gruppiert)
interface DeptBoardTicket {
  id: number; title: string; type_key: string; created_at: string
  status: string; priority: string
  phase_type: 'assignment' | 'department_review' | string
  phase_label: string
  department_id: string | null
}
interface DeptBoardGroup { group_id: string; group_name: string; tickets: DeptBoardTicket[] }
// Involviertes Ticket: wie DashboardTicket + Rollen des Nutzers
interface InvolvedTicket extends DashboardTicket { roles: string[] }
interface DashboardData {
  orders: DashboardTicket[]
  watched_orders: DashboardTicket[]
  department_board: DeptBoardGroup[]
  allowed_ticket_types: string[]
}

// ── State ─────────────────────────────────────────────────────────────────────
const loading   = ref(true)
const data      = ref<DashboardData>({ orders: [], watched_orders: [], department_board: [], allowed_ticket_types: [] })

// Involvierte Tickets (Archiv) – separat & lazy geladen
const involved        = ref<InvolvedTicket[]>([])
const involvedLoading = ref(false)
const involvedLoaded  = ref(false)

// ── Tabs ──────────────────────────────────────────────────────────────────────
type Tab = 'mine' | 'group' | 'watched' | 'involved'
const activeTab = ref<Tab>('mine')

// ── Filter ────────────────────────────────────────────────────────────────────
const filter = ref({ search: '', status: 'all', priority: 'all' })

// Beim Tab-Wechsel die Filter zurücksetzen
watch(activeTab, () => {
  filter.value = { search: '', status: 'all', priority: 'all' }
})

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

// Phasen-orientierte Bezeichnung (Status korreliert 1:1 mit der Phase):
// in_progress = Bearbeitung, in_request = Durchführung.
const STATUS_LABEL: Record<string, string> = {
  in_progress: 'Bearbeitung', in_request: 'Durchführung',
  archived: 'Archiviert', rejected: 'Abgelehnt',
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

// ── Rollen (Involviert-Tab) ─────────────────────────────────────────────────────
const ROLE_META: Record<string, { label: string; class: string }> = {
  ersteller:     { label: 'Ersteller',     class: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' },
  zustaendig:    { label: 'Zuständig',      class: 'bg-[#3EAAB8]/15 text-[#3EAAB8] dark:bg-[#3EAAB8]/20' },
  bearbeiter:    { label: 'Bearbeiter',     class: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' },
  fachabteilung: { label: 'Fachabteilung',  class: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300' },
  beobachter:    { label: 'Beobachter',     class: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' },
}
// stabile Reihenfolge der Chips
const ROLE_ORDER = ['zustaendig', 'bearbeiter', 'ersteller', 'fachabteilung', 'beobachter']
function sortedRoles(roles: string[]): string[] {
  return [...roles].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b))
}

async function loadInvolved() {
  if (involvedLoaded.value || involvedLoading.value) return
  involvedLoading.value = true
  try {
    const res = await client.get<{ data: { involved: InvolvedTicket[] } }>('/dashboard/involved')
    involved.value = res.data.data.involved ?? []
    involvedLoaded.value = true
  } finally {
    involvedLoading.value = false
  }
}

function selectInvolvedTab() {
  activeTab.value = 'involved'
  loadInvolved()
}

// ── Counts ────────────────────────────────────────────────────────────────────
const mineCount    = computed(() => (data.value.orders ?? []).filter(o => o.status !== 'archived' && o.status !== 'rejected').length)
const groupCount   = computed(() => (data.value.department_board ?? []).reduce((s, g) => s + g.tickets.length, 0))
const watchedCount = computed(() => (data.value.watched_orders ?? []).filter(o => o.status !== 'archived').length)
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
const filteredWatched = computed(() => applyFilter(data.value.watched_orders))
// Beobachter-Tab zeigt nur aktive Tickets – archivierte stehen jetzt unter „Involviert".
const filteredWatchedActive   = computed(() => filteredWatched.value.filter(o => o.status !== 'archived'))

// Involviert-Tab (Archiv) – durchsuchbar/filterbar wie die anderen
const filteredInvolved = computed(() => applyFilter(involved.value))
const involvedCount    = computed(() => involved.value.length)

// ── „Meine Abteilung" ──────────────────────────────────────────────────────────
// Vollständig vom Backend gruppiert: jede Abteilung genau einmal, jedes Ticket
// genau einmal in seiner aktuellen Phase. Frontend filtert nur noch.
const myDepartmentGroups = computed<DeptBoardGroup[]>(() =>
  (data.value.department_board ?? [])
    .map(g => ({ ...g, tickets: applyFilter(g.tickets) }))
    .filter(g => g.tickets.length > 0)
)

const currentCount = computed(() => {
  if (activeTab.value === 'mine') return filteredMine.value.length
  if (activeTab.value === 'group') return myDepartmentGroups.value.reduce((s, g) => s + g.tickets.length, 0)
  if (activeTab.value === 'involved') return filteredInvolved.value.length
  return filteredWatchedActive.value.length
})

// ── Actions ───────────────────────────────────────────────────────────────────
function openTicket(o: DashboardTicket) { router.push(`/tickets/view/${o.type_key}/${o.id}`) }
// Beobachter öffnen die read-only Gesamtansicht
function openWatchedTicket(o: DashboardTicket) { router.push(`/tickets/overview/${o.id}`) }
// Durchführung (department_id gesetzt) → ?department=<id> für die Aktionsleiste,
// Bearbeitung → Formular ohne department.
function openDeptItem(t: DeptBoardTicket) {
  const dep = t.department_id ? `?department=${t.department_id}` : ''
  router.push(`/tickets/view/${t.type_key}/${t.id}${dep}`)
}
function toggleGroupDept(id: string) { openGroupDepts.value[id] = !openGroupDepts.value[id] }

// ── Init ──────────────────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const res = await client.get<{ data: DashboardData }>('/dashboard')
    const d = res.data.data
    // Defensiv gegen fehlende Felder (z. B. veraltete Backend-Antwort)
    data.value = {
      orders:               d.orders ?? [],
      watched_orders:       d.watched_orders ?? [],
      department_board:     d.department_board ?? [],
      allowed_ticket_types: d.allowed_ticket_types ?? [],
    }
    // Auto-open department accordions
    for (const g of data.value.department_board) openGroupDepts.value[g.group_id] = true
    // Auto-select tab with most relevant content
    if (mineCount.value > 0) activeTab.value = 'mine'
    else if (groupCount.value > 0) activeTab.value = 'group'
    else if (watchedCount.value > 0) activeTab.value = 'watched'
  } finally {
    loading.value = false
  }
  // Involvierte Tickets im Hintergrund vorladen (für den Zähler), ohne den Render zu blockieren.
  loadInvolved()
})
</script>

<template>
  <AppLayout title="Übersicht">

    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else class="space-y-6">

      <!-- ── Header ── -->
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

      <!-- ── Stat Cards ── -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
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

        <button @click="activeTab = 'watched'" class="stat" :class="activeTab === 'watched' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
            </span>
            <span class="text-2xl font-bold text-gray-900 dark:text-white">{{ watchedCount }}</span>
          </div>
          <p class="stat-label">Beobachter</p>
        </button>

        <button @click="selectInvolvedTab" class="stat" :class="activeTab === 'involved' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </span>
            <span class="text-2xl font-bold text-gray-900 dark:text-white">
              <span v-if="involvedLoaded">{{ involvedCount }}</span>
              <span v-else class="inline-block w-4 h-4 rounded-full border-2 border-indigo-300 border-t-transparent animate-spin align-middle" />
            </span>
          </div>
          <p class="stat-label">Involviert</p>
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
              <option value="all">Alle Phasen</option>
              <option value="in_progress">Bearbeitung</option>
              <option value="in_request">Durchführung</option>
              <option value="archived">Archiviert</option>
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
                  <div v-for="t in g.tickets" :key="t.id" @click="openDeptItem(t)"
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
                      <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[t.priority]">{{ PRIORITY_LABEL[t.priority] }}</span>
                      <!-- Phasen-Badge ersetzt den (redundanten) Status-Badge -->
                      <span class="text-xs font-medium px-2.5 py-1 rounded-full"
                            :class="t.phase_type === 'department_review'
                              ? 'bg-[#3EAAB8]/10 text-[#3EAAB8] dark:bg-[#3EAAB8]/20'
                              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'">
                        {{ t.phase_label }}
                      </span>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <p v-if="myDepartmentGroups.length === 0" class="empty">Keine Aufträge für deine Abteilung.</p>
          </div>

          <!-- ═══ TAB: Beobachter (nur aktive – Archiv unter „Involviert") ═══ -->
          <div v-if="activeTab === 'watched'" class="max-h-[560px] overflow-auto">
            <ul class="divide-y divide-gray-100 dark:divide-white/[0.06]">
              <li v-for="o in filteredWatchedActive" :key="o.id" @click="openWatchedTicket(o)" class="row group">
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
              <li v-if="filteredWatchedActive.length === 0" class="empty">Du beobachtest keine offenen Tickets.</li>
            </ul>
          </div>

          <!-- ═══ TAB: Involviert (Archiv zum Zurückverfolgen) ═══ -->
          <div v-if="activeTab === 'involved'" class="max-h-[560px] overflow-auto">

            <!-- Ladezustand -->
            <div v-if="involvedLoading && !involvedLoaded" class="flex items-center justify-center py-14">
              <div class="w-6 h-6 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
            </div>

            <ul v-else class="divide-y divide-gray-100 dark:divide-white/[0.06]">
              <li v-for="o in filteredInvolved" :key="o.id" @click="openWatchedTicket(o)" class="row group">
                <div class="flex items-center gap-3.5 min-w-0">
                  <div class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(o.status)" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">{{ o.title }}</p>
                    <p class="text-xs text-gray-400 mt-0.5">{{ TYPE_LABEL[o.type_key] ?? o.type_key }} · {{ o.created_at }}</p>
                    <!-- Rollen-Chips: wie war ich beteiligt? -->
                    <div v-if="o.roles?.length" class="flex flex-wrap gap-1 mt-1.5">
                      <span v-for="r in sortedRoles(o.roles)" :key="r"
                            class="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                            :class="ROLE_META[r]?.class ?? 'bg-gray-100 text-gray-500'">
                        {{ ROLE_META[r]?.label ?? r }}
                      </span>
                    </div>
                  </div>
                </div>
                <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                  <span class="hidden sm:inline text-xs font-medium" :class="PRIORITY_CLASS[o.priority]">{{ PRIORITY_LABEL[o.priority] }}</span>
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="STATUS_CLASS[o.status]">{{ STATUS_LABEL[o.status] }}</span>
                  <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </li>
              <li v-if="filteredInvolved.length === 0" class="empty">
                {{ involvedLoaded ? 'Keine Tickets gefunden, an denen du beteiligt warst.' : 'Wird geladen…' }}
              </li>
            </ul>
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