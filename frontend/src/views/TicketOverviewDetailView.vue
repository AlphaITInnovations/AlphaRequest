<script setup lang="ts">
import { ref, onMounted, computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import { ticketsApi } from '@/api/tickets'
import { useAuthStore } from '@/stores/authStore'
import UserSelect from '@/components/UserSelect.vue'
import AppLayout from '@/components/AppLayout.vue'
import TicketHistoryTimeline from '@/views/TicketHistoryTimeline.vue'
import PhaseProgress from '@/components/tickets/PhaseProgress.vue'
import ZugangBeantragenContentPanel from '@/components/tickets/ZugangBeantragenContentPanel.vue'
// Weitere Panels hier importieren sobald sie erstellt wurden:
import ZugangSperrenContentPanel from '@/components/tickets/ZugangSperrenContentPanel.vue'
import HardwareContentPanel from '@/components/tickets/HardwareContentPanel.vue'
import NiederlassungAnmeldenContentPanel from '@/components/tickets/NiederlassungAnmeldenContentPanel.vue'
import NiederlassungUmzugContentPanel from '@/components/tickets/NiederlassungUmzugContentPanel.vue'
import NiederlassungSchliessenContentPanel from '@/components/tickets/NiederlassungSchliessenContentPanel.vue'
import MarketingStelleContentPanel from '@/components/tickets/MarketingStelleContentPanel.vue'
import HotelbuchungContentPanel from '@/components/tickets/HotelbuchungContentPanel.vue'
import BasisTicketContentPanel from '@/components/tickets/BasisTicketContentPanel.vue'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()
const id     = Number(route.params.id)

const loading = ref(true)
const data    = ref<any>(null)

const PANEL_MAP: Record<string, Component> = {
  'zugang-beantragen': ZugangBeantragenContentPanel,
  'zugang-sperren':           ZugangSperrenContentPanel,
  'hardware':                 HardwareContentPanel,
  'niederlassung-anmelden':   NiederlassungAnmeldenContentPanel,
  'niederlassung-umzug':      NiederlassungUmzugContentPanel,
  'niederlassung-schliessen': NiederlassungSchliessenContentPanel,
  'marketing-stellenanzeige': MarketingStelleContentPanel,
  'hotelbuchung':             HotelbuchungContentPanel,
  'basis-ticket':             BasisTicketContentPanel,
}

const contentPanel = computed(() =>
  data.value ? PANEL_MAP[data.value.type_key] ?? null : null
)

const STATUS_LABEL: Record<string, string> = {
  in_request:  'Zu bearbeiten',
  in_progress: 'In Bearbeitung',
  archived:    'Archiviert',
  rejected:    'Abgelehnt',
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
const DEPT_STATUS_LABEL: Record<string, string> = {
  done:        'Ausgeführt',
  open:        'Offen',
  in_progress: 'In Bearbeitung',
  rejected:    'Abgelehnt',
  skipped:     'Übersprungen',
}

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

async function load() {
  try {
    const { data: res } = await client.get(`/overview/tickets/${id}`)
    data.value = res.data
  } catch {
    // Kein Zugriff / nicht gefunden → zurück zum Dashboard (funktioniert auch
    // ohne globale view-Rolle; /tickets wäre für Nicht-Viewer gesperrt).
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ── Nachträge ──────────────────────────────────────────────────────────────
// Aus dem Verlauf extrahiert (action 'nachtrag_added'), neueste zuerst.
const nachtraege = computed<{ name: string; timestamp: string; text: string }[]>(() =>
  ((data.value?.history ?? []) as any[])
    .filter(e => e.action === 'nachtrag_added')
    .map(e => ({ name: e.actor?.name ?? 'System', timestamp: e.timestamp, text: e.details?.text ?? '' }))
    .reverse()
)
const showNachtrag    = ref(false)
const nachtragText    = ref('')
const nachtragSending = ref(false)
async function submitNachtrag() {
  const text = nachtragText.value.trim()
  if (!text) return
  nachtragSending.value = true
  try {
    await client.post(`/tickets/${id}/nachtrag`, { text })
    nachtragText.value = ''
    showNachtrag.value = false
    await load()
  } catch {
    alert('Nachtrag konnte nicht gespeichert werden.')
  } finally {
    nachtragSending.value = false
  }
}

// ── Admin: Zuständigkeit (Notfall) überschreiben ─────────────────────────────
const respSel    = ref<{ id: string; name: string } | null>(null)
const respSaving = ref(false)
async function saveResponsibility() {
  if (!respSel.value) return
  respSaving.value = true
  try {
    await ticketsApi.setResponsibility(id, respSel.value.id, respSel.value.name)
    respSel.value = null
    await load()
  } catch (e: any) {
    const msg = e?.response?.data?.error?.message
            ?? e?.response?.data?.detail
            ?? 'Zuständigkeit konnte nicht gesetzt werden (nur in einer Bearbeitungsphase möglich).'
    alert(msg)
  } finally {
    respSaving.value = false
  }
}

// Admin-Notfall: Bearbeitungs-Sperre aufheben (verhindert Lockout).
const unlocking = ref(false)
async function forceUnlock() {
  if (!confirm('Bearbeitungs-Sperre dieses Tickets aufheben?\n\nDie aktuell bearbeitende Person verliert dadurch ihre Sperre.')) return
  unlocking.value = true
  try {
    await ticketsApi.adminUnlock(id)
    await load()
  } catch {
    alert('Sperre konnte nicht aufgehoben werden.')
  } finally {
    unlocking.value = false
  }
}
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
        <button @click="router.push('/dashboard')"
                class="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/10
                       text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
          ← Zur Übersicht
        </button>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">

        <!-- ── Sidebar ── -->
        <aside class="space-y-4">

          <!-- Edit-Lock: wer bearbeitet gerade? (+ Admin-Notfall-Freigabe) -->
          <div v-if="data.lock?.locked"
               class="bg-amber-50 dark:bg-amber-400/10 border border-amber-300/70 dark:border-amber-400/25
                      rounded-2xl shadow-sm p-4 space-y-3">
            <div class="flex items-start gap-2.5">
              <span class="text-lg leading-none">🔒</span>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-amber-800 dark:text-amber-300">Wird gerade bearbeitet</p>
                <p class="text-xs text-amber-700 dark:text-amber-400/90 mt-0.5">
                  {{ data.lock.holder_name || 'Eine Person' }} bearbeitet dieses Ticket aktuell.
                </p>
              </div>
            </div>
            <button v-if="auth.isAdmin" @click="forceUnlock" :disabled="unlocking"
                    class="w-full px-4 py-2 rounded-xl text-sm font-medium
                           bg-amber-600 hover:bg-amber-700 text-white
                           disabled:opacity-50 disabled:cursor-not-allowed transition">
              {{ unlocking ? 'Wird aufgehoben…' : '🛠️ Sperre aufheben (Admin)' }}
            </button>
          </div>

          <!-- Fortschritt -->
          <div v-if="(data.phases ?? []).length"
               class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5">
            <PhaseProgress :phases="data.phases" />
          </div>

          <!-- Übersicht -->
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
            <div v-if="data.phase && data.phase !== '—'">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Phase</p>
              <span class="text-xs font-medium px-2.5 py-1 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8]">
                {{ data.phase }}
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

          <!-- Personen -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <div>
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Antragsteller</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.owner_name }}</p>
            </div>
            <div v-if="data.accountable_name" class="mt-3">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Verantwortlicher</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.accountable_name }}</p>
            </div>
            <div v-if="data.comment" class="mt-3">
              <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Kommentar</p>
              <p class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ data.comment }}</p>
            </div>
          </div>

          <!-- Admin: Zuständigkeit (Notfall) überschreiben -->
          <div v-if="auth.isAdmin && data.status !== 'archived'"
               class="bg-white dark:bg-[#212B3A] border border-orange-200/70 dark:border-orange-400/20
                      rounded-2xl shadow-sm p-5 text-sm">
            <div class="flex items-center gap-1.5 mb-1">
              <span class="text-base leading-none">🛠️</span>
              <p class="font-semibold text-gray-900 dark:text-white">Zuständigkeit ändern</p>
            </div>
            <p class="text-xs text-gray-400 mb-3">
              Admin-Notfall: setzt die Zuständigkeit der <strong>aktuellen Phase</strong> auf eine
              Person oder Fachabteilung. Wird im Verlauf protokolliert.
            </p>
            <UserSelect v-model="respSel" :show-groups="true" :show-users="true"
                        label="" placeholder="Person / Fachabteilung…" />
            <button @click="saveResponsibility" :disabled="!respSel || respSaving"
                    class="mt-3 w-full px-4 py-2 rounded-xl text-sm font-medium
                           bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                           disabled:opacity-50 disabled:cursor-not-allowed transition">
              {{ respSaving ? 'Wird gesetzt…' : 'Zuständigkeit setzen' }}
            </button>
          </div>

          <!-- Fachabteilungen -->
          <div v-if="Object.keys(data.departments ?? {}).length > 0"
               class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <p class="font-semibold text-gray-900 dark:text-white mb-3">Fachabteilungen</p>
            <ul class="space-y-2">
              <li v-for="(dept, gid) in data.departments" :key="gid"
                  class="flex items-center justify-between">
                <span class="text-gray-700 dark:text-gray-300">{{ dept.name }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                      :class="DEPT_CLASS[dept.status] ?? 'bg-gray-100 text-gray-500'">
                  {{ DEPT_STATUS_LABEL[dept.status] ?? dept.status }}
                </span>
              </li>
            </ul>
          </div>
        </aside>

        <!-- ── Main Content ── -->
        <section class="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-5 items-start">

          <!-- Auftragsinhalt -->
          <div class="space-y-5">
            <!-- Nachträge (nur bei archivierten Aufträgen) – ganz oben, direkt sichtbar -->
            <div v-if="data.status === 'archived'"
                 class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                        rounded-2xl shadow-sm p-6 space-y-4">
              <div class="flex items-center justify-between">
                <h2 class="text-base font-semibold text-gray-900 dark:text-white">
                  Nachträge
                  <span v-if="nachtraege.length" class="text-gray-400 font-normal">· {{ nachtraege.length }}</span>
                </h2>
                <button v-if="!showNachtrag" @click="showNachtrag = true"
                        class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-sm font-medium
                               bg-[#3EAAB8]/10 text-[#3EAAB8] hover:bg-[#3EAAB8]/20 transition">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                    <path stroke-linecap="round" d="M12 5v14m7-7H5"/>
                  </svg>
                  Nachtrag
                </button>
              </div>

              <!-- Eingabe -->
              <div v-if="showNachtrag"
                   class="space-y-2 rounded-xl border border-[#3EAAB8]/30 bg-[#3EAAB8]/5 p-3">
                <textarea v-model="nachtragText" rows="4" autofocus
                          placeholder="Nachtrag verfassen…"
                          class="w-full rounded-lg border border-gray-200 dark:border-white/10
                                 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                                 placeholder-gray-400 px-3.5 py-2.5 text-sm resize-none
                                 focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-xs text-gray-400">
                    Beim Speichern werden die beteiligten Fachabteilungen per Mail informiert.
                  </p>
                  <div class="flex gap-2 flex-shrink-0">
                    <button @click="showNachtrag = false; nachtragText = ''"
                            class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                                   text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
                      Abbrechen
                    </button>
                    <button @click="submitNachtrag" :disabled="!nachtragText.trim() || nachtragSending"
                            class="px-4 py-2 text-sm rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white font-medium
                                   disabled:opacity-50 disabled:cursor-not-allowed transition">
                      {{ nachtragSending ? 'Wird gesendet…' : 'Speichern' }}
                    </button>
                  </div>
                </div>
              </div>

              <!-- Liste -->
              <div v-if="nachtraege.length" class="space-y-3">
                <div v-for="(n, i) in nachtraege" :key="i"
                     class="rounded-xl border border-gray-100 dark:border-white/[0.06]
                            bg-gray-50 dark:bg-[#1A2130] p-3.5">
                  <div class="flex items-center justify-between mb-1.5">
                    <span class="text-sm font-medium text-gray-900 dark:text-white">{{ n.name }}</span>
                    <span class="text-xs text-gray-400">{{ formatDate(n.timestamp) }}</span>
                  </div>
                  <p class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ n.text }}</p>
                </div>
              </div>
              <p v-else-if="!showNachtrag" class="text-sm text-gray-400 italic">Noch keine Nachträge.</p>
            </div>

            <!-- Auftragsinhalt -->
            <!-- Dediziertes Panel vorhanden → rendern -->
            <component
              v-if="contentPanel"
              :is="contentPanel"
              :description="data.description"
            />

            <!-- Fallback: generischer JSON-Renderer -->
            <div v-else
                 class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                        rounded-2xl shadow-sm p-6 space-y-3">
              <h2 class="text-base font-semibold text-gray-900 dark:text-white">Auftragsinhalt</h2>
              <template v-if="data.description && Object.keys(data.description).length > 0">
                <details v-for="(section, key) in data.description" :key="key"
                         class="border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden">
                  <summary class="cursor-pointer px-4 py-3 font-medium text-sm
                                  text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/5">
                    {{ String(key).replace(/_/g, ' ').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) }}
                  </summary>
                  <div class="p-4 border-t border-gray-100 dark:border-white/[0.04]">
                    <DescriptionRenderer :value="section" />
                  </div>
                </details>
              </template>
              <p v-else class="text-sm text-gray-400 italic">Keine Auftragsdaten vorhanden.</p>
            </div>
          </div>

          <!-- Verlauf -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 xl:sticky xl:top-4 max-h-[75vh] overflow-auto">
            <TicketHistoryTimeline :history="data.history" />
          </div>

        </section>
      </div>
    </div>
  </AppLayout>
</template>

<script lang="ts">
import { defineComponent, h } from 'vue'

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
            : 'px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 font-medium',
        }, val ? 'Ja' : 'Nein')
      }
      if (Array.isArray(val)) {
        if (val.length === 0) return h('span', { class: 'text-gray-400' }, '—')
        return h('div', { class: 'space-y-2' },
          val.map((item, i) => h('div', {
            key: i,
            class: 'border border-gray-200 dark:border-white/[0.06] rounded-lg p-3',
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
                : 'border border-gray-200 dark:border-white/[0.06] rounded-xl p-3',
            }, isComplex ? [
              h('div', { class: 'px-4 py-2 bg-gray-50 dark:bg-white/5 border-b border-gray-200 dark:border-white/[0.06] text-xs font-semibold text-gray-500 uppercase tracking-wider' },
                k.replace(/_/g, ' ')),
              h('div', { class: 'p-4' }, [render(v)])
            ] : [
              h('p', { class: 'text-xs text-gray-400 mb-1' }, k.replace(/_/g, ' ')),
              render(v),
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
  },
})
</script>