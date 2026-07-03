<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { client } from '@/api/client'

interface AuditEntry {
  id: number
  created_at: string
  actor_id: string | null
  actor_name: string | null
  actor_type: string
  action: string
  entity_type: string | null
  entity_id: string | null
  summary: string | null
  details: Record<string, any>
  ip: string | null
}

const entries  = ref<AuditEntry[]>([])
const total    = ref(0)
const actions  = ref<string[]>([])
const loading  = ref(true)
const expanded = ref<number | null>(null)

// ── Filter & Paging ──────────────────────────────────────────────────────────
const fAction     = ref('')
const fEntityType = ref('')
const fActor      = ref('')
const fSearch     = ref('')
const fFrom       = ref('')   // Datum von (YYYY-MM-DD)
const fTo         = ref('')   // Datum bis (inkl. ganzem Tag)
const pageSize    = 25
const offset      = ref(0)

const page       = computed(() => Math.floor(offset.value / pageSize) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const ACTION_LABEL: Record<string, string> = {
  ticket_created: 'Ticket erstellt', ticket_updated: 'Ticket bearbeitet', ticket_deleted: 'Ticket gelöscht',
  ticket_submitted: 'Übergeben', ticket_rejected: 'Abgelehnt', ticket_archived_manual: 'Archiviert',
  phase_advanced: 'Phase weiter', status_changed: 'Status geändert',
  responsibility_overridden: 'Zuständigkeit (Admin)', lock_released: 'Sperre aufgehoben',
  admin_raw_edited: 'Raw-Bearbeitung', department_status_changed: 'Fachabteilung', nachtrag_added: 'Nachtrag',
  freigabe_approved_mail: 'Freigegeben (Mail)', freigabe_rejected_mail: 'Abgelehnt (Mail)',
  login: 'Login', logout: 'Logout', admin_granted: 'Admin gewährt', admin_revoked: 'Admin entzogen',
  user_role_changed: 'Rolle geändert', user_permissions_set: 'Rechte gesetzt',
  user_permission_added: 'Recht hinzugefügt', user_permission_removed: 'Recht entfernt',
  companies_changed: 'Firmen geändert', ticket_permissions_changed: 'Ticket-Rechte',
  group_created: 'Gruppe erstellt', group_deleted: 'Gruppe gelöscht',
}
function actionLabel(a: string) { return ACTION_LABEL[a] ?? a }

const ENTITY_ICON: Record<string, string> = {
  ticket: '🎫', auth: '🔑', user: '👤', settings: '⚙️', group: '🏢',
}

function entityText(e: AuditEntry) {
  if (!e.entity_type) return '—'
  if (e.entity_type === 'ticket') return `Ticket #${e.entity_id}`
  return e.entity_id ? `${e.entity_type}: ${e.entity_id}` : e.entity_type
}

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/settings/audit-log', {
      params: {
        limit: pageSize, offset: offset.value,
        action: fAction.value || undefined,
        entity_type: fEntityType.value || undefined,
        actor: fActor.value || undefined,
        q: fSearch.value || undefined,
        since: fFrom.value || undefined,
        until: fTo.value || undefined,
      },
    })
    entries.value = data.data.entries
    total.value   = data.data.total
    actions.value = data.data.actions
  } finally {
    loading.value = false
  }
}

// Filterwechsel → zurück auf Seite 1 (debounced für Textfelder).
let t: ReturnType<typeof setTimeout> | null = null
watch([fAction, fEntityType, fActor, fSearch, fFrom, fTo], () => {
  if (t) clearTimeout(t)
  t = setTimeout(() => { offset.value = 0; load() }, 250)
})
watch(offset, load)

function prev() { if (offset.value > 0) offset.value -= pageSize }
function next() { if (page.value < totalPages.value) offset.value += pageSize }
function toggle(id: number) { expanded.value = expanded.value === id ? null : id }
function resetFilters() {
  fAction.value = ''; fEntityType.value = ''; fActor.value = ''; fSearch.value = ''
  fFrom.value = ''; fTo.value = ''
}

onMounted(load)
</script>

<template>
  <section>
    <h2 class="section-title">Audit-Log</h2>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Revisionssicheres Protokoll aller wichtigen Aktionen (Ticket-Erstellung/-Änderung/-Löschung,
      Logins, Rollen- und Rechte-Änderungen) – jeweils mit Zeitpunkt und ausführender Person.
      Einträge bleiben auch nach dem Löschen eines Tickets erhalten.
    </div>

    <!-- Filter -->
    <div class="flex flex-wrap items-center gap-2 mb-4">
      <input v-model="fSearch" placeholder="Suche (Zusammenfassung, Details…)" class="afi flex-1 min-w-[12rem]" />
      <select v-model="fAction" class="afi">
        <option value="">Alle Aktionen</option>
        <option v-for="a in actions" :key="a" :value="a">{{ actionLabel(a) }}</option>
      </select>
      <select v-model="fEntityType" class="afi">
        <option value="">Alle Objekte</option>
        <option value="ticket">Tickets</option>
        <option value="auth">Auth</option>
        <option value="user">Benutzer</option>
        <option value="settings">Einstellungen</option>
        <option value="group">Gruppen</option>
      </select>
      <input v-model="fActor" placeholder="Person…" class="afi" />
      <div class="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
        <span>Von</span>
        <input v-model="fFrom" type="date" class="afi" />
        <span>bis</span>
        <input v-model="fTo" type="date" class="afi" />
      </div>
      <button @click="resetFilters"
              class="px-3 py-2 rounded-xl text-sm text-gray-500 dark:text-gray-400
                     border border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5 transition">
        Zurücksetzen
      </button>
    </div>

    <div class="card-section !p-0 overflow-hidden">
      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-gray-400 uppercase tracking-wider border-b dark:border-white/[0.06]">
            <th class="px-4 py-3">Zeitpunkt</th>
            <th class="px-4 py-3">Aktion</th>
            <th class="px-4 py-3">Person</th>
            <th class="px-4 py-3">Objekt</th>
            <th class="px-4 py-3">Details</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <template v-for="e in entries" :key="e.id">
            <tr class="hover:bg-gray-50 dark:hover:bg-[#263040] transition cursor-pointer align-top"
                @click="toggle(e.id)">
              <td class="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">{{ formatDate(e.created_at) }}</td>
              <td class="px-4 py-3">
                <span class="text-xs font-medium px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] whitespace-nowrap">
                  {{ actionLabel(e.action) }}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-700 dark:text-gray-200">
                <span v-if="e.actor_type === 'system'" class="text-gray-400">⚙️ System</span>
                <span v-else>{{ e.actor_name || '—' }}</span>
              </td>
              <td class="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-300">
                <span class="mr-1">{{ ENTITY_ICON[e.entity_type ?? ''] ?? '' }}</span>{{ entityText(e) }}
              </td>
              <td class="px-4 py-3 text-gray-600 dark:text-gray-300 max-w-[24rem] truncate">
                {{ e.summary || '—' }}
              </td>
            </tr>
            <tr v-if="expanded === e.id" class="bg-gray-50 dark:bg-[#1A2130]">
              <td colspan="5" class="px-4 py-3">
                <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  <span v-if="e.actor_id">Actor-ID: <span class="font-mono">{{ e.actor_id }}</span> · </span>
                  <span v-if="e.ip">IP: <span class="font-mono">{{ e.ip }}</span> · </span>
                  <span class="font-mono">#{{ e.id }}</span>
                </div>
                <pre class="text-xs whitespace-pre-wrap break-words text-gray-700 dark:text-gray-300
                            bg-white dark:bg-[#212B3A] rounded-lg border border-gray-100 dark:border-white/[0.06] p-3">{{ JSON.stringify(e.details, null, 2) }}</pre>
              </td>
            </tr>
          </template>
          <tr v-if="entries.length === 0">
            <td colspan="5" class="px-4 py-12 text-center text-sm text-gray-400 italic">Keine Einträge gefunden</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Paging -->
    <div class="flex items-center justify-between text-sm text-gray-400 mt-3">
      <span>{{ total }} Einträge · Seite {{ page }} von {{ totalPages }}</span>
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
@reference "../style.css";
.section-title { @apply text-lg font-semibold text-gray-900 dark:text-white mb-4; }
.card-section  { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-5; }
.afi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
