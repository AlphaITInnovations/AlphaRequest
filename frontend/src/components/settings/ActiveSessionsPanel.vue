<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { sessionsApi, type ActiveSession } from '@/api/sessions'

const sessions   = ref<ActiveSession[]>([])
const loading    = ref(false)
const busy       = ref(false)
const lastLoaded = ref<Date | null>(null)
const nowTick    = ref(Date.now())
const live       = ref(true)

const ONLINE_THRESHOLD_S = 90

// ── Laden ────────────────────────────────────────────────────────────────────
let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  try {
    const { data } = await sessionsApi.list()
    if (my !== reqId) return
    sessions.value = data.data.sessions
    lastLoaded.value = new Date()
  } finally {
    if (my === reqId) loading.value = false
  }
}

// ── Force-Logout ───────────────────────────────────────────────────────────────
async function revoke(s: ActiveSession) {
  if (busy.value) return
  const who = s.user_name || s.user_id
  if (!confirm(`Session von „${who}" wirklich abmelden?`)) return
  busy.value = true
  try {
    await sessionsApi.revokeSession(s.sid)
    await load()
  } finally {
    busy.value = false
  }
}

async function logoutOthers() {
  if (busy.value) return
  const others = sessions.value.filter(s => !s.current).length
  if (others === 0) return
  if (!confirm(`Alle anderen Sessions (${others}) abmelden? Ihre eigene bleibt aktiv.`)) return
  busy.value = true
  try {
    await sessionsApi.logoutOthers()
    await load()
  } finally {
    busy.value = false
  }
}

// ── Zeit / Präsenz (Client-berechnet für flüssige Live-Anzeige) ─────────────────
function ageSeconds(ts: string): number {
  if (!ts) return Infinity
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const then = new Date(s).getTime()
  if (isNaN(then)) return Infinity
  return Math.max(0, Math.round((nowTick.value - then) / 1000))
}
function isOnline(s: ActiveSession): boolean {
  return ageSeconds(s.last_seen) < ONLINE_THRESHOLD_S
}
function relativeTime(ts: string): string {
  const sec = ageSeconds(ts)
  if (!isFinite(sec)) return '—'
  if (sec < 60) return 'gerade eben'
  const min = Math.round(sec / 60)
  if (min < 60) return `vor ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `vor ${h} h`
  return `vor ${Math.round(h / 24)} d`
}
function formatDate(ts: string): string {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ── Gerät/Browser aus User-Agent (grobe, freundliche Kurzform) ──────────────────
function shortAgent(ua: string | null): string {
  if (!ua) return '—'
  const browser =
    /Edg\//.test(ua) ? 'Edge' :
    /OPR\/|Opera/.test(ua) ? 'Opera' :
    /Chrome\//.test(ua) ? 'Chrome' :
    /Firefox\//.test(ua) ? 'Firefox' :
    /Safari\//.test(ua) ? 'Safari' : ''
  const os =
    /Windows/.test(ua) ? 'Windows' :
    /iPhone|iPad|iOS/.test(ua) ? 'iOS' :
    /Mac OS X|Macintosh/.test(ua) ? 'macOS' :
    /Android/.test(ua) ? 'Android' :
    /Linux/.test(ua) ? 'Linux' : ''
  const parts = [browser, os].filter(Boolean)
  return parts.length ? parts.join(' · ') : ua.slice(0, 40)
}

// ── Live-Refresh + Tick ─────────────────────────────────────────────────────────
let liveTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null
function startLive() {
  stopLive()
  liveTimer = setInterval(() => { if (!busy.value) load() }, 10_000)
}
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null } }

onMounted(() => {
  load()
  startLive()
  tickTimer = setInterval(() => { nowTick.value = Date.now() }, 10_000)
})
onUnmounted(() => {
  stopLive()
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<template>
  <section>
    <div class="flex items-center justify-between gap-3 flex-wrap mb-1">
      <h2 class="section-title mb-0">Aktive Sessions</h2>
      <div class="flex items-center gap-3">
        <span v-if="lastLoaded" class="text-xs text-gray-400">aktualisiert {{ relativeTime(lastLoaded.toISOString()) }}</span>
        <label class="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none">
          <input type="checkbox" v-model="live" @change="live ? startLive() : stopLive()"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30" />
          <span class="inline-flex items-center gap-1">
            <span v-if="live" class="w-2 h-2 rounded-full bg-green-500 animate-pulse" /> Live
          </span>
        </label>
        <button @click="logoutOthers" :disabled="busy || sessions.filter(s => !s.current).length === 0"
                class="px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition
                       border border-red-300/60 text-red-700 dark:text-red-300
                       bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30
                       disabled:opacity-40 disabled:cursor-not-allowed">
          Alle anderen abmelden
        </button>
      </div>
    </div>

    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Zeigt alle aktuell angemeldeten Nutzer. „Online" bedeutet: in den letzten
      {{ ONLINE_THRESHOLD_S }} Sekunden aktiv (offener Tab zählt via Heartbeat).
      Über „Abmelden" wird die betreffende Sitzung sofort beendet – der Nutzer landet
      beim nächsten Seitenaufruf wieder auf der Anmeldung.
    </div>

    <div class="card-section !p-0 overflow-hidden">
      <div v-if="loading && sessions.length === 0" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-gray-400 uppercase tracking-wider border-b dark:border-white/[0.06]">
            <th class="px-4 py-3">Status</th>
            <th class="px-4 py-3">Benutzer</th>
            <th class="px-4 py-3">IP</th>
            <th class="px-4 py-3">Gerät</th>
            <th class="px-4 py-3">Angemeldet</th>
            <th class="px-4 py-3">Zuletzt aktiv</th>
            <th class="px-4 py-3 text-right">Aktion</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <tr v-for="s in sessions" :key="s.sid"
              class="align-top" :class="s.current ? 'bg-[#3EAAB8]/[0.06]' : ''">
            <td class="px-4 py-3 whitespace-nowrap">
              <span v-if="isOnline(s)" class="inline-flex items-center gap-1.5 text-xs font-medium text-green-600 dark:text-green-400">
                <span class="w-2 h-2 rounded-full bg-green-500" /> Online
              </span>
              <span v-else class="inline-flex items-center gap-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                <span class="w-2 h-2 rounded-full bg-amber-400" /> Inaktiv
              </span>
            </td>
            <td class="px-4 py-3">
              <div class="font-medium text-gray-900 dark:text-white">
                {{ s.user_name || '—' }}
                <span v-if="s.current" class="ml-1 text-xs font-normal text-[#3EAAB8]">(Sie)</span>
              </div>
              <div class="font-mono text-xs text-gray-400 truncate max-w-[16rem]">{{ s.user_id }}</div>
            </td>
            <td class="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">{{ s.ip || '—' }}</td>
            <td class="px-4 py-3 text-gray-600 dark:text-gray-300 whitespace-nowrap">{{ shortAgent(s.user_agent) }}</td>
            <td class="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
              <span :title="formatDate(s.created_at)">{{ relativeTime(s.created_at) }}</span>
            </td>
            <td class="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
              <span :title="formatDate(s.last_seen)">{{ relativeTime(s.last_seen) }}</span>
            </td>
            <td class="px-4 py-3 text-right whitespace-nowrap">
              <span v-if="s.current" class="text-xs text-gray-400 italic">aktuelle Sitzung</span>
              <button v-else @click="revoke(s)" :disabled="busy"
                      class="px-3 py-1.5 rounded-lg text-xs font-medium transition
                             text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20
                             disabled:opacity-40 disabled:cursor-not-allowed">
                Abmelden
              </button>
            </td>
          </tr>
          <tr v-if="sessions.length === 0 && !loading">
            <td colspan="7" class="px-4 py-12 text-center text-sm text-gray-400 italic">Keine aktiven Sessions</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="text-xs text-gray-400 mt-3">{{ sessions.length }} aktive Session(s)</p>
  </section>
</template>
