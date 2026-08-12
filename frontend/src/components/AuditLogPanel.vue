<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
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

const router = useRouter()

const entries  = ref<AuditEntry[]>([])
const total    = ref(0)
const actions  = ref<string[]>([])
const loading  = ref(false)
const expanded = ref<number | null>(null)
const lastLoaded = ref<Date | null>(null)
const nowTick    = ref(Date.now())

// ── Filter & Paging ──────────────────────────────────────────────────────────
const fAction     = ref('')
const fEntityType = ref('')
const fActor      = ref('')
const fSearch     = ref('')
const pageSize    = 25
const offset      = ref(0)

// ── Zeitbereich (Grafana-Stil) ─────────────────────────────────────────────────
type Range = '1h' | '24h' | '7d' | '30d' | 'all' | 'custom'
const range = ref<Range>('24h')
const RANGE_LABEL: Record<Range, string> = {
  '1h': 'Letzte Stunde', '24h': 'Letzte 24 h', '7d': 'Letzte 7 Tage',
  '30d': 'Letzte 30 Tage', 'all': 'Alle', 'custom': 'Benutzerdefiniert',
}
const RANGE_MS: Record<string, number> = {
  '1h': 3600e3, '24h': 24 * 3600e3, '7d': 7 * 24 * 3600e3, '30d': 30 * 24 * 3600e3,
}
const fFrom = ref('')   // custom von (YYYY-MM-DD)
const fTo   = ref('')   // custom bis

// Naive-UTC-ISO (Sekunden), passend zum gespeicherten created_at-Format.
function isoSecondsAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString().slice(0, 19)
}
const sinceParam = computed<string | undefined>(() => {
  if (range.value === 'all') return undefined
  if (range.value === 'custom') return fFrom.value || undefined
  return isoSecondsAgo(RANGE_MS[range.value])
})
const untilParam = computed<string | undefined>(() =>
  range.value === 'custom' ? (fTo.value || undefined) : undefined)

const page       = computed(() => Math.floor(offset.value / pageSize) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// ── Aktions-Metadaten (Label + Schweregrad) ─────────────────────────────────────
//
// Das Audit-Log ist append-only: Einträge des entfernten Alt-Systems bleiben in
// der Tabelle. Ihre Beschriftungen stehen deshalb weiter hier – ohne sie zeigte
// das Panel für alte Zeilen nur noch den rohen Schlüssel.
const ACTION_LABEL: Record<string, string> = {
  // ── Prozess-Aufträge ──
  // Namen aus backend/services/process_events.py: `process_ticket_<action>` für
  // jeden Verlaufs-Eintrag (jedes Ereignis wird zusätzlich auditiert).
  process_ticket_created: 'Auftrag erstellt',
  process_ticket_updated: 'Angaben geändert',
  process_ticket_advanced: 'Phase weiter',
  process_ticket_rejected: 'Auftrag abgelehnt',
  process_ticket_reopened: 'Auftrag wieder aufgenommen',
  process_ticket_comment: 'Nachtrag',
  process_ticket_department_done: 'Fachabteilung erledigt',
  process_ticket_department_skipped: 'Fachabteilung nicht zuständig',
  process_ticket_department_rejected: 'Fachabteilung abgelehnt',
  process_ticket_watcher_added: 'Beobachter:in eingetragen',
  process_ticket_watcher_removed: 'Beobachtung beendet',
  process_ticket_automation_fired: 'Automation ausgeführt',
  process_ticket_priority_changed: 'Priorität geändert',
  process_ticket_approval_decided: 'Freigabe entschieden',
  process_ticket_approval_sent_back: 'Zur Nachbesserung zurück',
  process_ticket_approval_no_recipient: 'Freigabe-Mail ohne Empfänger',
  process_ticket_deleted: 'Auftrag gelöscht',
  // Direkte Audit-Einträge ohne Verlaufs-Eintrag (System-Pfade)
  process_approval_decided: 'Freigabe entschieden (Mail-Link)',
  process_approval_no_recipient: 'Freigabe-Mail ohne Empfänger',
  process_phase_notified: 'Phase benachrichtigt',
  process_automation_fired: 'Automation ausgeführt',
  process_automation_failed: 'Automation fehlgeschlagen',
  process_timer_stamp_failed: 'Timer konnte nicht gesetzt werden',
  // ── Prozess-Definitionen ──
  process_created: 'Prozess erstellt', process_draft_created: 'Entwurf angelegt',
  process_draft_updated: 'Entwurf gespeichert', process_published: 'Prozess veröffentlicht',
  process_duplicated: 'Prozess kopiert', process_imported: 'Prozess importiert',
  process_version_deleted: 'Version gelöscht',
  // ── System / Rechte ──
  login: 'Login', logout: 'Logout', login_failed: 'Login fehlgeschlagen', session_revoked: 'Session abgemeldet',
  admin_granted: 'Admin gewährt', admin_revoked: 'Admin entzogen', access_denied: 'Zugriff verweigert',
  user_role_changed: 'Rolle geändert', user_permissions_set: 'Rechte gesetzt',
  user_permission_added: 'Recht hinzugefügt', user_permission_removed: 'Recht entfernt',
  companies_changed: 'Firmen geändert',
  group_created: 'Gruppe erstellt', group_deleted: 'Gruppe gelöscht', group_updated: 'Gruppe geändert',
  group_member_added: 'Mitglied hinzugefügt', group_member_removed: 'Mitglied entfernt',
  personalnummer_assigned: 'Personalnr. vergeben', personalnummer_range_low: 'Personalnr. fast erschöpft',
  personalnummer_exhausted: 'Personalnr. erschöpft',
  // ── Alt-System (nur noch historische Einträge) ──
  ticket_created: 'Ticket erstellt', ticket_updated: 'Ticket bearbeitet', ticket_deleted: 'Ticket gelöscht',
  ticket_submitted: 'Übergeben', ticket_rejected: 'Abgelehnt', ticket_archived_manual: 'Archiviert',
  phase_advanced: 'Phase weiter', status_changed: 'Status geändert',
  responsibility_overridden: 'Zuständigkeit (Admin)', lock_released: 'Sperre aufgehoben',
  admin_raw_edited: 'Raw-Bearbeitung', department_status_changed: 'Fachabteilung', nachtrag_added: 'Nachtrag',
  freigabe_approved_mail: 'Freigegeben (Mail)', freigabe_rejected_mail: 'Abgelehnt (Mail)',
  ticket_permissions_changed: 'Erstellrechte geändert',
}
function actionLabel(a: string) { return ACTION_LABEL[a] ?? a }

type Severity = 'danger' | 'warning' | 'success' | 'info' | 'neutral'
const SEVERITY: Record<string, Severity> = {
  // ── Prozess-Aufträge ──
  process_ticket_deleted: 'danger', process_ticket_rejected: 'danger',
  process_ticket_department_rejected: 'danger',
  process_ticket_approval_no_recipient: 'danger', process_approval_no_recipient: 'danger',
  process_automation_failed: 'danger', process_timer_stamp_failed: 'danger',
  process_ticket_reopened: 'warning', process_ticket_approval_sent_back: 'warning',
  process_ticket_automation_fired: 'warning', process_automation_fired: 'warning',
  process_ticket_created: 'success', process_ticket_advanced: 'success',
  process_ticket_department_done: 'success',
  process_ticket_updated: 'info', process_ticket_comment: 'info',
  process_ticket_department_skipped: 'info', process_ticket_priority_changed: 'info',
  process_ticket_watcher_added: 'info', process_ticket_watcher_removed: 'info',
  process_ticket_approval_decided: 'info', process_approval_decided: 'info',
  process_phase_notified: 'info',
  // ── Prozess-Definitionen: Veröffentlichen und Löschen sind die Eingriffe, die
  //    auf ALLE künftigen Aufträge wirken – die müssen herausstechen. ──
  process_version_deleted: 'danger',
  process_published: 'warning', process_imported: 'warning',
  process_created: 'success', process_duplicated: 'success',
  process_draft_created: 'info', process_draft_updated: 'info',
  // ── System / Rechte ──
  access_denied: 'danger', login_failed: 'danger',
  personalnummer_exhausted: 'danger', admin_revoked: 'danger', group_deleted: 'danger',
  session_revoked: 'warning', personalnummer_range_low: 'warning',
  group_member_removed: 'warning', user_permission_removed: 'warning',
  personalnummer_assigned: 'success', admin_granted: 'success',
  group_created: 'success', group_member_added: 'success', user_permission_added: 'success',
  login: 'info', logout: 'info', user_role_changed: 'info', user_permissions_set: 'info',
  companies_changed: 'info', group_updated: 'info',
  // ── Alt-System (nur noch historische Einträge) ──
  ticket_deleted: 'danger', ticket_rejected: 'danger', freigabe_rejected_mail: 'danger',
  responsibility_overridden: 'warning', admin_raw_edited: 'warning', lock_released: 'warning',
  ticket_created: 'success', freigabe_approved_mail: 'success',
  ticket_updated: 'info', phase_advanced: 'info', ticket_submitted: 'info',
  ticket_archived_manual: 'info', department_status_changed: 'info', nachtrag_added: 'info',
  status_changed: 'info', ticket_permissions_changed: 'info',
}
function severity(a: string): Severity { return SEVERITY[a] ?? 'neutral' }

const BADGE_CLASS: Record<Severity, string> = {
  danger:  'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  warning: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  success: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  info:    'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  neutral: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
}
const BORDER_CLASS: Record<Severity, string> = {
  danger: 'border-l-red-500', warning: 'border-l-amber-500', success: 'border-l-green-500',
  info: 'border-l-[#3EAAB8]', neutral: 'border-l-gray-300 dark:border-l-white/20',
}

const ENTITY_ICON: Record<string, string> = {
  process_ticket: '🎫', process_definition: '🧩',
  auth: '🔑', user: '👤', settings: '⚙️', group: '🏢',
  // Alt-System: Einträge bleiben im append-only Log, sind aber nicht mehr öffenbar.
  ticket: '🗄️',
}

function entityText(e: AuditEntry) {
  if (!e.entity_type) return '—'
  if (e.entity_type === 'process_ticket') return `Auftrag #${e.entity_id}`
  if (e.entity_type === 'process_definition') return `Prozess: ${e.entity_id}`
  if (e.entity_type === 'ticket') return `Alt-Ticket #${e.entity_id}`
  return e.entity_id ? `${e.entity_type}: ${e.entity_id}` : e.entity_type
}

/**
 * Nur Prozess-Aufträge haben eine Zielseite. Alt-Ticket-Einträge bleiben im Log
 * stehen (append-only), führen aber nirgendwohin – auf /prozess-auftraege/:id zu
 * verweisen wäre falsch, die ID gehört zu einem anderen Auftrag. Prozess-
 * DEFINITIONEN haben ebenfalls keinen Verweis: der Editor braucht `key` UND
 * `version`, im Audit steht nur der Key.
 */
function canOpen(e: AuditEntry): boolean {
  return e.entity_type === 'process_ticket' && !!e.entity_id
}
function openEntity(e: AuditEntry) {
  if (canOpen(e)) router.push(`/prozess-auftraege/${e.entity_id}`)
}

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function relativeTime(ts: string): string {
  if (!ts) return ''
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const then = new Date(s).getTime()
  if (isNaN(then)) return ''
  const sec = Math.max(0, Math.round((nowTick.value - then) / 1000))
  if (sec < 60) return 'gerade eben'
  const min = Math.round(sec / 60)
  if (min < 60) return `vor ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `vor ${h} h`
  return `vor ${Math.round(h / 24)} d`
}

// ── Laden ────────────────────────────────────────────────────────────────────
let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  try {
    const { data } = await client.get('/settings/audit-log', {
      params: {
        limit: pageSize, offset: offset.value,
        action: fAction.value || undefined,
        entity_type: fEntityType.value || undefined,
        actor: fActor.value || undefined,
        q: fSearch.value || undefined,
        since: sinceParam.value,
        until: untilParam.value,
      },
    })
    if (my !== reqId) return
    entries.value = data.data.entries
    total.value   = data.data.total
    actions.value = data.data.actions
    lastLoaded.value = new Date()
  } finally {
    if (my === reqId) loading.value = false
  }
}

let debounce: ReturnType<typeof setTimeout> | null = null
watch([fAction, fEntityType, fActor, fSearch, range, fFrom, fTo], () => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => { offset.value = 0; load() }, 250)
})
watch(offset, load)

// ── Live-Refresh ───────────────────────────────────────────────────────────────
const live = ref(true)
let liveTimer: ReturnType<typeof setInterval> | null = null
function startLive() {
  stopLive()
  liveTimer = setInterval(() => {
    // Nicht stören, wenn ein Detail offen ist oder man auf Seite >1 blättert.
    if (expanded.value === null && offset.value === 0) load()
  }, 10_000)
}
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null } }
watch(live, v => { v ? startLive() : stopLive() })

let tickTimer: ReturnType<typeof setInterval> | null = null

function prev() { if (offset.value > 0) offset.value -= pageSize }
function next() { if (page.value < totalPages.value) offset.value += pageSize }
function toggle(id: number) { expanded.value = expanded.value === id ? null : id }
function resetFilters() {
  fAction.value = ''; fEntityType.value = ''; fActor.value = ''; fSearch.value = ''
  range.value = '24h'; fFrom.value = ''; fTo.value = ''
}

// ── CSV-Export (gefilterte Menge, seitenübergreifend, bis Cap) ──────────────────
const exporting = ref(false)
async function exportCsv() {
  exporting.value = true
  try {
    const CAP = 5000, batch = 200
    const rows: AuditEntry[] = []
    let off = 0
    while (rows.length < CAP) {
      const { data } = await client.get('/settings/audit-log', {
        params: {
          limit: batch, offset: off,
          action: fAction.value || undefined, entity_type: fEntityType.value || undefined,
          actor: fActor.value || undefined, q: fSearch.value || undefined,
          since: sinceParam.value, until: untilParam.value,
        },
      })
      const got: AuditEntry[] = data.data.entries
      rows.push(...got)
      if (got.length < batch || rows.length >= data.data.total) break
      off += batch
    }
    const esc = (v: any) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const header = ['Zeitpunkt', 'Aktion', 'Person', 'Actor-ID', 'Objekt-Typ', 'Objekt-ID', 'Zusammenfassung', 'IP', 'Details']
    const lines = rows.map(e => [
      formatDate(e.created_at), actionLabel(e.action), e.actor_name ?? '', e.actor_id ?? '',
      e.entity_type ?? '', e.entity_id ?? '', e.summary ?? '', e.ip ?? '', JSON.stringify(e.details ?? {}),
    ].map(esc).join(','))
    const csv = '﻿' + [header.map(esc).join(','), ...lines].join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-log_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  load()
  startLive()
  tickTimer = setInterval(() => { nowTick.value = Date.now() }, 30_000)
})
onUnmounted(() => {
  stopLive()
  if (tickTimer) clearInterval(tickTimer)
  if (debounce) clearTimeout(debounce)
})
</script>

<template>
  <section>
    <div class="flex items-center justify-between gap-3 flex-wrap mb-1">
      <h2 class="section-title mb-0">Audit-Log</h2>
      <div class="flex items-center gap-3">
        <span v-if="lastLoaded" class="text-xs text-gray-400">aktualisiert {{ relativeTime(lastLoaded.toISOString()) }}</span>
        <label class="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none">
          <input type="checkbox" v-model="live" class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30" />
          <span class="inline-flex items-center gap-1">
            <span v-if="live" class="w-2 h-2 rounded-full bg-green-500 animate-pulse" /> Live
          </span>
        </label>
        <button @click="exportCsv" :disabled="exporting" class="btn-secondary text-xs py-1.5">
          {{ exporting ? 'Export…' : '⬇ CSV' }}
        </button>
      </div>
    </div>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Revisionssicheres Protokoll aller wichtigen Aktionen – mit Zeitpunkt und ausführender Person.
      Einträge bleiben auch nach dem Löschen eines Auftrags erhalten; Einträge des entfernten
      Alt-Systems ebenfalls, sie führen aber auf keine Seite mehr.
    </div>

    <!-- Filter -->
    <div class="flex flex-wrap gap-2 items-center mb-2">
      <input v-model="fSearch" placeholder="Suche (Zusammenfassung, Details…)" class="afi flex-1 min-w-[12rem]" />
      <select v-model="fAction" class="afi">
        <option value="">Alle Aktionen</option>
        <option v-for="a in actions" :key="a" :value="a">{{ actionLabel(a) }}</option>
      </select>
      <select v-model="fEntityType" class="afi">
        <option value="">Alle Objekte</option>
        <option value="process_ticket">Prozess-Aufträge</option>
        <option value="process_definition">Prozesse</option>
        <option value="auth">Auth</option>
        <option value="user">Benutzer</option>
        <option value="settings">Einstellungen</option>
        <option value="group">Gruppen</option>
        <option value="ticket">Alt-System (Archiv)</option>
      </select>
      <input v-model="fActor" placeholder="Person…" class="afi" />
      <select v-model="range" class="afi" title="Zeitbereich">
        <option v-for="(lbl, key) in RANGE_LABEL" :key="key" :value="key">{{ lbl }}</option>
      </select>
      <button @click="resetFilters"
              class="px-3 py-2 rounded-xl text-sm text-gray-500 dark:text-gray-400
                     border border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5 transition">
        Zurücksetzen
      </button>
    </div>
    <div v-if="range === 'custom'" class="flex items-center gap-2 mb-4 text-sm text-gray-500 dark:text-gray-400">
      <span>Von</span><input v-model="fFrom" type="date" class="afi" />
      <span>bis</span><input v-model="fTo" type="date" class="afi" />
    </div>
    <div v-else class="mb-4" />

    <div class="card-section !p-0 overflow-hidden">
      <div v-if="loading && entries.length === 0" class="flex items-center justify-center py-16">
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
            <tr class="hover:bg-gray-50 dark:hover:bg-[#263040] transition cursor-pointer align-top border-l-4"
                :class="BORDER_CLASS[severity(e.action)]" @click="toggle(e.id)">
              <td class="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
                <span :title="formatDate(e.created_at)">{{ relativeTime(e.created_at) }}</span>
              </td>
              <td class="px-4 py-3">
                <span class="text-xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap" :class="BADGE_CLASS[severity(e.action)]">
                  {{ actionLabel(e.action) }}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-700 dark:text-gray-200">
                <span v-if="e.actor_type === 'system'" class="text-gray-400">⚙️ System</span>
                <span v-else>{{ e.actor_name || '—' }}</span>
              </td>
              <td class="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-300">
                <button v-if="canOpen(e)" @click.stop="openEntity(e)"
                        class="text-[#3EAAB8] hover:underline">
                  {{ ENTITY_ICON[e.entity_type ?? ''] ?? '' }} {{ entityText(e) }}
                </button>
                <span v-else><span class="mr-1">{{ ENTITY_ICON[e.entity_type ?? ''] ?? '' }}</span>{{ entityText(e) }}</span>
              </td>
              <td class="px-4 py-3 text-gray-600 dark:text-gray-300 max-w-[24rem] truncate">{{ e.summary || '—' }}</td>
            </tr>
            <tr v-if="expanded === e.id" class="bg-gray-50 dark:bg-[#1A2130]">
              <td colspan="5" class="px-4 py-3">
                <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
                  <span>{{ formatDate(e.created_at) }} · </span>
                  <span v-if="e.actor_id">Actor-ID: <span class="font-mono">{{ e.actor_id }}</span> · </span>
                  <span v-if="e.ip">IP: <span class="font-mono">{{ e.ip }}</span> · </span>
                  <span class="font-mono">#{{ e.id }}</span>
                </div>
                <pre class="text-xs whitespace-pre-wrap break-words text-gray-700 dark:text-gray-300
                            bg-white dark:bg-[#212B3A] rounded-lg border border-gray-100 dark:border-white/[0.06] p-3">{{ JSON.stringify(e.details, null, 2) }}</pre>
              </td>
            </tr>
          </template>
          <tr v-if="entries.length === 0 && !loading">
            <td colspan="5" class="px-4 py-12 text-center text-sm text-gray-400 italic">Keine Einträge gefunden</td>
          </tr>
        </tbody>
      </table>
    </div>

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
.afi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
