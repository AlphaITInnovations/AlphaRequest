<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketsApi } from '@/api/tickets'
import AppLayout from '@/components/AppLayout.vue'
import TicketDetailBody from '@/components/tickets/TicketDetailBody.vue'
import UserSelect from '@/components/UserSelect.vue'

const route  = useRoute()
const router = useRouter()
const id     = Number(route.params.id)

const loading = ref(true)
const data    = ref<any>(null)

async function load() {
  try {
    const { data: res } = await ticketsApi.adminDetail(id)
    data.value = res.data
  } catch {
    router.push('/tickets')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const isArchived = computed(() => data.value?.status === 'archived')
const isTerminal = computed(() => ['archived', 'rejected'].includes(data.value?.status))
const phases     = computed<any[]>(() => data.value?.phases ?? [])
// Wiedereröffnen nur in Bearbeitungs-/Durchführungsphasen – die Erstellungsphase
// ist kein gültiges Ziel (ließe sich nicht weiterschalten).
const reopenablePhases = computed<any[]>(() =>
  phases.value.map((p, i) => ({ ...p, _idx: i })).filter((p) => p.type !== 'creation'))

function errMsg(e: any, fallback: string) {
  return e?.response?.data?.error?.message ?? e?.response?.data?.detail ?? fallback
}

// ── Zuständigkeit ändern ─────────────────────────────────────────────────────
const showResp   = ref(false)
const respSel    = ref<{ id: string; name: string } | null>(null)
const respSaving = ref(false)
async function saveResponsibility() {
  if (!respSel.value) return
  respSaving.value = true
  try {
    await ticketsApi.setResponsibility(id, respSel.value.id, respSel.value.name)
    respSel.value = null
    showResp.value = false
    await load()
  } catch (e: any) {
    alert(errMsg(e, 'Zuständigkeit konnte nicht gesetzt werden (nur in einer Bearbeitungsphase möglich).'))
  } finally {
    respSaving.value = false
  }
}

// ── Wiedereröffnen (nur archiviert) ──────────────────────────────────────────
const showReopen   = ref(false)
const reopenIdx    = ref<number | null>(null)
const reopenResp   = ref<{ id: string; name: string } | null>(null)
const reopenDept   = ref<Record<string, boolean>>({})   // group_id -> wieder öffnen?
const reopenSaving = ref(false)
const reopenError  = ref('')

const reopenPhase = computed<any | null>(() =>
  reopenIdx.value !== null ? (phases.value[reopenIdx.value] ?? null) : null)

function onReopenPhaseChange() {
  reopenResp.value = null
  reopenDept.value = {}
  reopenError.value = ''
  const p = reopenPhase.value
  if (p?.type === 'department_review' && p.departments) {
    for (const gid of Object.keys(p.departments)) reopenDept.value[gid] = false
  }
}

function toggleReopen() {
  showReopen.value = !showReopen.value
  if (showReopen.value) { reopenIdx.value = null; onReopenPhaseChange() }
}

async function saveReopen() {
  const p = reopenPhase.value
  if (!p || reopenIdx.value === null) { reopenError.value = 'Bitte eine Zielphase wählen.'; return }
  const payload: { phase_index: number; assignee_id?: string; assignee_name?: string; departments?: Record<string, string> } =
    { phase_index: reopenIdx.value }

  if (p.type === 'department_review') {
    const depts: Record<string, string> = {}
    let anyOpen = false
    for (const gid of Object.keys(p.departments ?? {})) {
      const open = !!reopenDept.value[gid]
      depts[gid] = open ? 'open' : 'done'
      if (open) anyOpen = true
    }
    if (!anyOpen) { reopenError.value = 'Mindestens eine Fachabteilung muss wieder geöffnet werden.'; return }
    payload.departments = depts
  } else if (p.type === 'assignment') {
    if (!reopenResp.value) { reopenError.value = 'Bitte eine zuständige Person/Fachabteilung wählen.'; return }
    payload.assignee_id = reopenResp.value.id
    payload.assignee_name = reopenResp.value.name
  }

  reopenSaving.value = true
  reopenError.value = ''
  try {
    await ticketsApi.reopen(id, payload)
    showReopen.value = false
    reopenIdx.value = null
    await load()
  } catch (e: any) {
    reopenError.value = errMsg(e, 'Wiedereröffnen fehlgeschlagen.')
  } finally {
    reopenSaving.value = false
  }
}

// ── Sperre aufheben ──────────────────────────────────────────────────────────
const unlocking = ref(false)
async function forceUnlock() {
  if (!confirm('Bearbeitungs-Sperre dieses Tickets aufheben?\n\nDie aktuell bearbeitende Person verliert dadurch ihre Sperre.')) return
  unlocking.value = true
  try {
    await ticketsApi.adminUnlock(id)
    await load()
  } catch (e: any) {
    alert(errMsg(e, 'Sperre konnte nicht aufgehoben werden.'))
  } finally {
    unlocking.value = false
  }
}

// ── Archivieren ──────────────────────────────────────────────────────────────
const archiving = ref(false)
async function archive() {
  if (!confirm('Dieses Ticket archivieren?')) return
  archiving.value = true
  try {
    await ticketsApi.archive(id)
    await load()
  } catch (e: any) {
    alert(errMsg(e, 'Ticket konnte nicht archiviert werden.'))
  } finally {
    archiving.value = false
  }
}

// ── Löschen (Hard-Delete) ────────────────────────────────────────────────────
const deleting = ref(false)
async function removeTicket() {
  if (!confirm(`Ticket #${id} endgültig löschen?\n\nDas kann NICHT rückgängig gemacht werden. Beobachter und Sperren werden mit entfernt.`)) return
  deleting.value = true
  try {
    await ticketsApi.adminDelete(id)
    router.push('/tickets')
  } catch (e: any) {
    alert(errMsg(e, 'Ticket konnte nicht gelöscht werden.'))
    deleting.value = false
  }
}

// ── Raw-JSON-Editor ──────────────────────────────────────────────────────────
const PRIORITIES = ['low', 'medium', 'high', 'critical']
const STATUSES   = ['in_progress', 'in_request', 'archived', 'rejected']

const showRaw   = ref(false)
const rawSaving = ref(false)
const rawForm   = ref({ description: '', title: '', comment: '', priority: '', status: '' })
const rawError  = ref('')

function openRaw() {
  const d = data.value
  let descText = ''
  try {
    descText = JSON.stringify(d.description ?? {}, null, 2)
  } catch {
    descText = d.description_raw ?? '{}'
  }
  rawForm.value = {
    description: descText,
    title: d.title ?? '',
    comment: d.comment ?? '',
    priority: d.priority ?? 'medium',
    status: d.status ?? 'in_progress',
  }
  rawError.value = ''
  showRaw.value = true
}

async function saveRaw() {
  // JSON clientseitig vorprüfen (früher Fehler statt 400).
  try {
    JSON.parse(rawForm.value.description || '{}')
  } catch {
    rawError.value = 'Die description ist kein gültiges JSON.'
    return
  }
  rawSaving.value = true
  rawError.value = ''
  try {
    await ticketsApi.rawUpdate(id, {
      description: rawForm.value.description,
      title: rawForm.value.title,
      comment: rawForm.value.comment,
      priority: rawForm.value.priority,
      status: rawForm.value.status,
    })
    showRaw.value = false
    await load()
  } catch (e: any) {
    rawError.value = errMsg(e, 'Speichern fehlgeschlagen.')
  } finally {
    rawSaving.value = false
  }
}
</script>

<template>
  <AppLayout title="Ticket — Admin">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <div class="flex items-center gap-2">
            <p class="text-sm text-gray-400">Ticket #{{ data.id }}</p>
            <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full
                         bg-orange-100 text-orange-700 dark:bg-orange-400/15 dark:text-orange-300">Admin</span>
          </div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white mt-0.5">{{ data.title }}</h1>
        </div>
        <button @click="router.push('/tickets')"
                class="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/10
                       text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
          ← Zur Liste
        </button>
      </div>

      <!-- ── Admin-Aktionen (prominent, oben) ── -->
      <div class="rounded-2xl border border-orange-300/60 dark:border-orange-400/25
                  bg-orange-50/70 dark:bg-orange-400/[0.07] shadow-sm p-5 space-y-4">
        <div class="flex items-center gap-2">
          <span class="text-lg leading-none">🛠️</span>
          <h2 class="font-semibold text-gray-900 dark:text-white">Admin-Aktionen</h2>
          <span class="text-xs text-gray-500 dark:text-gray-400">— Notfall-Werkzeuge, alle Änderungen werden protokolliert</span>
        </div>

        <div class="flex flex-wrap gap-2">
          <button v-if="!isTerminal" @click="showResp = !showResp"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         bg-[#3EAAB8] hover:bg-[#2B7D89] text-white transition">
            👤 Zuständigkeit ändern
          </button>
          <button v-if="isArchived" @click="toggleReopen"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         bg-emerald-600 hover:bg-emerald-700 text-white transition">
            🔓 Wiedereröffnen
          </button>
          <button v-if="data.lock?.locked" @click="forceUnlock" :disabled="unlocking"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         bg-amber-600 hover:bg-amber-700 text-white disabled:opacity-50 transition">
            🔓 {{ unlocking ? 'Wird aufgehoben…' : 'Sperre aufheben' }}
          </button>
          <button @click="openRaw"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         border border-gray-300 dark:border-white/15 text-gray-700 dark:text-gray-200
                         hover:bg-white dark:hover:bg-white/5 transition">
            🧬 Raw-JSON bearbeiten
          </button>
          <button v-if="!isArchived" @click="archive" :disabled="archiving"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         border border-gray-300 dark:border-white/15 text-gray-700 dark:text-gray-200
                         hover:bg-white dark:hover:bg-white/5 disabled:opacity-50 transition">
            🗄️ {{ archiving ? 'Wird archiviert…' : 'Archivieren' }}
          </button>
          <button @click="removeTicket" :disabled="deleting"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium
                         bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 transition ml-auto">
            🗑️ {{ deleting ? 'Wird gelöscht…' : 'Löschen' }}
          </button>
        </div>

        <!-- Zuständigkeit ändern (ausklappbar) -->
        <div v-if="showResp"
             class="rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#212B3A] p-4 space-y-3">
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Setzt die Zuständigkeit der <strong>aktuellen Phase</strong> auf eine Person oder Fachabteilung.
          </p>
          <UserSelect v-model="respSel" :show-groups="true" :show-users="true"
                      label="" placeholder="Person / Fachabteilung…" />
          <div class="flex justify-end gap-2">
            <button @click="showResp = false; respSel = null"
                    class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                           text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
              Abbrechen
            </button>
            <button @click="saveResponsibility" :disabled="!respSel || respSaving"
                    class="px-4 py-2 text-sm rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white font-medium
                           disabled:opacity-50 disabled:cursor-not-allowed transition">
              {{ respSaving ? 'Wird gesetzt…' : 'Zuständigkeit setzen' }}
            </button>
          </div>
        </div>

        <!-- Wiedereröffnen (ausklappbar, nur archiviert) -->
        <div v-if="showReopen"
             class="rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#212B3A] p-4 space-y-3">
          <p class="text-xs text-gray-500 dark:text-gray-400">
            Archivierten Auftrag in eine gewählte Phase wiedereröffnen. Je nach Phase sind
            Zusatzangaben nötig (Fachabteilungen bzw. Zuständigkeit).
          </p>

          <label class="block">
            <span class="text-xs text-gray-400 uppercase tracking-wider">Zielphase</span>
            <select v-model.number="reopenIdx" @change="onReopenPhaseChange"
                    class="mt-1 w-full rounded-lg border border-gray-200 dark:border-white/10
                           bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30">
              <option :value="null" disabled>Phase wählen…</option>
              <option v-for="p in reopenablePhases" :key="p._idx" :value="p._idx">{{ p._idx + 1 }}. {{ p.label }}</option>
            </select>
          </label>

          <!-- Durchführung: Fachabteilungen wählen -->
          <div v-if="reopenPhase && reopenPhase.type === 'department_review'" class="space-y-2">
            <p class="text-xs text-gray-500 dark:text-gray-400">
              Welche Fachabteilungen sollen <strong>wieder geöffnet</strong> werden?
              Nicht gewählte bleiben „erledigt".
            </p>
            <label v-for="(d, gid) in (reopenPhase.departments || {})" :key="gid"
                   class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
              <input type="checkbox" v-model="reopenDept[gid]"
                     class="rounded border-gray-300 text-[#3EAAB8] focus:ring-[#3EAAB8]/30" />
              <span>{{ d.name }}</span>
              <span v-if="d.status === 'done'" class="text-[10px] text-gray-400">(war: erledigt)</span>
            </label>
          </div>

          <!-- Bearbeitungsphase: Zuständigkeit wählen -->
          <div v-else-if="reopenPhase && reopenPhase.type === 'assignment'" class="space-y-2">
            <p class="text-xs text-gray-500 dark:text-gray-400">Wer ist in dieser Phase zuständig?</p>
            <UserSelect v-model="reopenResp" :show-groups="true" :show-users="true"
                        label="" placeholder="Person / Fachabteilung…" />
          </div>

          <p v-if="reopenError" class="text-sm text-red-600 dark:text-red-400">{{ reopenError }}</p>

          <div class="flex justify-end gap-2">
            <button @click="showReopen = false"
                    class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                           text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
              Abbrechen
            </button>
            <button @click="saveReopen" :disabled="reopenSaving || reopenIdx === null"
                    class="px-4 py-2 text-sm rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium
                           disabled:opacity-50 disabled:cursor-not-allowed transition">
              {{ reopenSaving ? 'Wird wiedereröffnet…' : 'Wiedereröffnen' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Read-only Detail -->
      <TicketDetailBody :data="data" @reload="load" />
    </div>

    <!-- ── Raw-JSON-Editor (Modal) ── -->
    <div v-if="showRaw" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/50" @click="showRaw = false" />
      <div class="relative w-full max-w-2xl max-h-[90vh] overflow-auto rounded-2xl
                  bg-white dark:bg-[#212B3A] border border-gray-200 dark:border-white/10 shadow-xl p-6 space-y-4">
        <div class="flex items-center gap-2">
          <span class="text-lg">🧬</span>
          <h3 class="font-semibold text-gray-900 dark:text-white">Raw-Bearbeitung (Notfall)</h3>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          Direkte Bearbeitung der Rohdaten. Nur mit Bedacht verwenden — die <code>description</code> muss
          gültiges JSON bleiben. Die Zuständigkeit ändert man über den Button oben, nicht hier.
        </p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-gray-400 uppercase tracking-wider">Titel</span>
            <input v-model="rawForm.title" type="text"
                   class="mt-1 w-full rounded-lg border border-gray-200 dark:border-white/10
                          bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm
                          focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
          </label>
          <label class="block">
            <span class="text-xs text-gray-400 uppercase tracking-wider">Priorität</span>
            <select v-model="rawForm.priority"
                    class="mt-1 w-full rounded-lg border border-gray-200 dark:border-white/10
                           bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30">
              <option v-for="p in PRIORITIES" :key="p" :value="p">{{ p }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-gray-400 uppercase tracking-wider">Status</span>
            <select v-model="rawForm.status"
                    class="mt-1 w-full rounded-lg border border-gray-200 dark:border-white/10
                           bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30">
              <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-gray-400 uppercase tracking-wider">Kommentar</span>
            <input v-model="rawForm.comment" type="text"
                   class="mt-1 w-full rounded-lg border border-gray-200 dark:border-white/10
                          bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm
                          focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
          </label>
        </div>

        <label class="block">
          <span class="text-xs text-gray-400 uppercase tracking-wider">description (JSON)</span>
          <textarea v-model="rawForm.description" rows="14" spellcheck="false"
                    class="mt-1 w-full font-mono text-xs rounded-lg border border-gray-200 dark:border-white/10
                           bg-white dark:bg-[#1A2130] text-gray-900 dark:text-gray-100 px-3 py-2 resize-y
                           focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
        </label>

        <p v-if="rawError" class="text-sm text-red-600 dark:text-red-400">{{ rawError }}</p>

        <div class="flex justify-end gap-2">
          <button @click="showRaw = false"
                  class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                         text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
            Abbrechen
          </button>
          <button @click="saveRaw" :disabled="rawSaving"
                  class="px-4 py-2 text-sm rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white font-medium
                         disabled:opacity-50 transition">
            {{ rawSaving ? 'Wird gespeichert…' : 'Speichern' }}
          </button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
