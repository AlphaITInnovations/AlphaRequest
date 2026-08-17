<script setup lang="ts">
/**
 * Übersicht: die Arbeitslisten der angemeldeten Person über alle Prozess-Aufträge.
 *
 * ZWEI Quellen, absichtlich:
 *
 *  1. `GET /dashboard` → Block `process` (backend/api/v1/dashboard.py). Gelesen
 *     werden `process.my`, `process.involved` und `process.counts`; dazu
 *     `my_departments` für die Namen und IDs der eigenen Fachabteilungen. Der
 *     Block ist bewusst WERTEFREI (keine Feldwerte, §5.1) und trägt deshalb auch
 *     keine Zuständigkeit mit.
 *
 *  2. `GET /process-tickets` → vollständige `ProcessTicketOut`-Zeilen. Nur die
 *     tragen `responsibility` (mit dem LIVE-Stand der Fachabteilungen) – ohne sie
 *     lässt sich „wartet auf MEINE Abteilung" nicht beantworten, und genau das
 *     ist die Frage, für die es lib/processDepartments.ts gibt.
 *
 * Beide Aufrufe sind voneinander unabhängig abgesichert: fällt einer aus, bleiben
 * die Listen des anderen sichtbar. Der Server filtert in beiden Fällen selbst,
 * wer was sehen darf – hier wird nichts nachgebaut.
 */
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import { listTickets } from '@/api/processTickets'
import { errorMessage } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import {
  departmentProgress, isTicketTerminal,
  ticketsAwaitingAnyDepartment, ticketsAwaitingDepartment,
} from '@/lib/processDepartments'
import type { ProcessTicketOut } from '@/types/process'

const router = useRouter()
const auth   = useAuthStore()

// ── Antwort-Formen (nur das, was hier gelesen wird) ───────────────────────────

/** Zeile des Prozess-Blocks (`ProcessDashboardTicket` im Backend). */
interface ProcessOrder {
  id: number
  process_key: string
  process_version: number
  title: string
  status: string
  priority: string
  phase: string | null
  phase_label: string | null
  /** true = von mir angelegt (sonst: ich bin beteiligt/zuständig). */
  is_owner: boolean
  created_at: string
  updated_at: string
}
interface ProcessBlock {
  my: ProcessOrder[]
  involved: ProcessOrder[]
  /** Ausdrücklich beobachtet – vom Server GETRENNT von `involved` geliefert. */
  watched: ProcessOrder[]
  /** Anzahl je Status – nur über die für mich sichtbaren Aufträge. */
  counts: Record<string, number>
}
interface DepartmentRef { id: string; name: string }

// ── Zustand ───────────────────────────────────────────────────────────────────

const loading = ref(true)
const block = ref<ProcessBlock>({ my: [], involved: [], watched: [], counts: {} })
const myDepartments = ref<DepartmentRef[]>([])
const blockError = ref<string | null>(null)

const rows = ref<ProcessTicketOut[]>([])
const rowsLoading = ref(true)
const rowsError = ref<string | null>(null)
/** Obergrenze des Endpunkts – mehr gibt es nicht in einem Rutsch. */
const ROWS_LIMIT = 200
const rowsTotal = ref(0)

// ── Reiter ────────────────────────────────────────────────────────────────────

type Tab = 'assigned' | 'departments' | 'watched' | 'involved'
const activeTab = ref<Tab>('assigned')

function selectTab(tab: Tab) {
  activeTab.value = tab
}

// ── Beschriftungen ────────────────────────────────────────────────────────────
// Status- und Prioritäts-Whitelist kommen aus lib/processSchema.ts (Spiegel des
// Backends). Unbekannte Werte werden ROH gezeigt – eine erfundene Beschriftung
// wäre eine Falschaussage über den echten Stand.

const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  in_request:  'bg-[#3EAAB8]/10 text-[#3EAAB8] dark:bg-[#3EAAB8]/20',
  waiting_contract: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
  archived:    'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
}
const DOT_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-400', in_request: 'bg-[#3EAAB8]',
  waiting_contract: 'bg-violet-400', archived: 'bg-gray-400', rejected: 'bg-red-500',
}

function statusLabel(s: string) { return STATUS_LABEL[s] ?? s }
function statusClass(s: string) {
  return STATUS_CLASS[s] ?? 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400'
}
// Die Priorität wird derzeit ÜBERALL ausgeblendet (Feld, API und Zeilen-Daten
// bleiben – nur die Anzeige ruht, bis geklärt ist, wie sie sinnvoll eingesetzt
// wird). Deshalb gibt es hier keine Prioritäts-Beschriftungen mehr.
function dotClass(s: string) { return DOT_CLASS[s] ?? 'bg-gray-300' }

/** ISO-Datum (JJJJ-MM-TT) deutsch – ohne Zeitzonen-Umrechnung, der Wert ist ein
 *  Kalendertag. Ein längerer Zeitstempel wird vorne abgeschnitten. */
function fmtDay(iso: string | null) {
  const p = (iso || '').slice(0, 10).split('-')
  return p.length === 3 ? `${p[2]}.${p[1]}.${p[0]}` : (iso || '—')
}

// ── Gemeinsame Zeilen-Form für die Darstellung ────────────────────────────────
// Die zwei Quellen haben verschiedene Formen; die Liste zeigt beide gleich.

interface Zeile {
  id: number
  title: string
  process_key: string
  status: string
  priority: string
  phase_label: string | null
  created_at: string | null
  /** Zusatz-Plakette rechts (z. B. „Ersteller"), optional. */
  badge?: { text: string; class: string }
  /** Quittier-Fortschritt („2 von 3 erledigt"), nur im Abteilungs-Reiter. */
  depts?: { text: string }
}

function zeileAusBlock(o: ProcessOrder): Zeile {
  return {
    id: o.id, title: o.title, process_key: o.process_key,
    status: o.status, priority: o.priority,
    phase_label: o.phase_label, created_at: o.created_at,
  }
}

function zeileAusRow(t: ProcessTicketOut): Zeile {
  return {
    id: t.id, title: t.title, process_key: t.process_key,
    status: t.status, priority: t.priority,
    phase_label: t.current_phase_label, created_at: t.created_at,
  }
}

// ── Arbeitslisten ─────────────────────────────────────────────────────────────

const meineId = computed(() => auth.user?.id ?? null)
const meineGruppen = computed(() => myDepartments.value.map((d) => d.id))
/** Aufsichts-Rollen (viewer/manager/admin) – nur sie dürfen zur Auftragsliste. */
const hatAufsicht = computed(() => auth.canView || auth.canManage || auth.isAdmin)

/** Aktive Aufträge – terminale (abgelehnt/archiviert) gehören in keine Arbeitsliste. */
const aktiveRows = computed(() => rows.value.filter((t) => !isTicketTerminal(t)))

/**
 * Mir PERSÖNLICH zugewiesen: die aufgelöste Zuständigkeit nennt genau mich.
 * `assignable` löst der Server zu kind='user' auf, deshalb genügt dieser Fall.
 * Aufträge, in denen ich als Ersteller:in am Zug bin (kind='owner'), zählen mit –
 * auch das ist Arbeit, die auf mich wartet.
 */
const mirZugewiesen = computed<ProcessTicketOut[]>(() => {
  const uid = meineId.value
  if (!uid) return []
  return aktiveRows.value.filter((t) => {
    const r = t.responsibility
    if (!r) return false
    if (r.kind === 'user') return r.user === uid
    if (r.kind === 'owner') return t.owner_id === uid
    return false
  })
})

/** Wartet auf eine Fachabteilung, in der ich Mitglied bin (Logik: processDepartments). */
const meineAbteilungen = computed(() =>
  ticketsAwaitingAnyDepartment(aktiveRows.value, meineGruppen.value))

/** Zeile für den Abteilungs-Reiter: der Quittier-Fortschritt kommt nur bei
 *  echten Quittier-Phasen dazu – bei einfacher Gruppen-Zuständigkeit (z. B.
 *  Basis-Ticket) sagt schon der Abschnitts-Kopf, wo der Auftrag liegt. */
function zeileFuerAbteilung(t: ProcessTicketOut): Zeile {
  const r = t.responsibility
  const z = zeileAusRow(t)
  if (r && r.kind === 'departments') {
    z.depts = { text: departmentProgress(r.departments ?? []).text }
  }
  return z
}

/**
 * Reiter „Meine Abteilungen": nach Fachabteilung GRUPPIERT – dieselbe
 * Warte-Logik wie die Kachel (awaitsDepartment, inkl. einfacher
 * Gruppen-Zuständigkeit). Ein Auftrag, der auf MEHRERE meiner Abteilungen
 * wartet, erscheint in jedem betroffenen Abschnitt: jede Abteilung sieht
 * ihre Arbeitsliste vollständig.
 */
const abteilungsGruppen = computed(() =>
  myDepartments.value.map((d) => ({
    id: d.id,
    name: d.name,
    zeilen: ticketsAwaitingDepartment(aktiveRows.value, d.id).map(zeileFuerAbteilung),
  })))

const abteilungenMitAufgaben = computed(() =>
  abteilungsGruppen.value.filter((g) => g.zeilen.length))

// ── Arbeitslisten ─────────────────────────────────────────────────────────────
// Bewusst OHNE Filterleiste: das Dashboard beantwortet „was liegt bei mir an?".
// Suchen und Filtern über alle Aufträge ist die Aufgabe der Übersicht
// (views/OverviewView.vue) – zwei Ansichten mit derselben Filterleiste hatten sich
// gegenseitig die Aussage genommen.

const zeilenAssigned = computed(() => mirZugewiesen.value.map(zeileAusRow))

const zeilenInvolved = computed(() =>
  block.value.involved.map((o) => ({
    ...zeileAusBlock(o),
    badge: { text: 'Beteiligt', class: 'bg-[#3EAAB8]/15 text-[#3EAAB8] dark:bg-[#3EAAB8]/20' },
  })))

const zeilenWatched = computed(() =>
  block.value.watched.map((o) => ({
    ...zeileAusBlock(o),
    badge: { text: 'Beobachtet', class: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' },
  })))

const zeilen = computed<Zeile[]>(() => {
  switch (activeTab.value) {
    case 'assigned':    return zeilenAssigned.value
    case 'watched':     return zeilenWatched.value
    default:            return zeilenInvolved.value
  }
})

/**
 * EINE Render-Liste für alle Reiter, damit die Zeilen überall dasselbe Markup
 * haben: der Abteilungs-Reiter streut Abschnitts-Köpfe je Fachabteilung ein,
 * alle anderen liefern nur Zeilen.
 */
type AnzeigeElement =
  | { art: 'kopf'; key: string; id: string; name: string; anzahl: number; zu: boolean }
  | { art: 'zeile'; key: string; z: Zeile }

/** Zugeklappte Abteilungs-Abschnitte – reiner Anzeige-Zustand dieses Besuchs. */
const zugeklappt = ref<Record<string, boolean>>({})
function abschnittUmklappen(id: string) {
  zugeklappt.value = { ...zugeklappt.value, [id]: !zugeklappt.value[id] }
}

const anzeige = computed<AnzeigeElement[]>(() => {
  if (activeTab.value !== 'departments') {
    return zeilen.value.map((z) => ({ art: 'zeile', key: `${activeTab.value}-${z.id}`, z }))
  }
  return abteilungenMitAufgaben.value.flatMap((g): AnzeigeElement[] => {
    const zu = !!zugeklappt.value[g.id]
    return [
      { art: 'kopf', key: `kopf-${g.id}`, id: g.id, name: g.name,
        anzahl: g.zeilen.length, zu },
      ...(zu ? [] : g.zeilen.map((z): AnzeigeElement => (
        { art: 'zeile', key: `${g.id}-${z.id}`, z }))),
    ]
  })
})

// ── Zähler für die Kacheln (ungefiltert) ──────────────────────────────────────

const countAssigned    = computed(() => mirZugewiesen.value.length)
const countDepartments = computed(() => meineAbteilungen.value.length)
const countInvolved    = computed(() => block.value.involved.length)
const countWatched     = computed(() => block.value.watched.length)
const offeneAufgaben   = computed(() => countAssigned.value + countDepartments.value)

/** Status-Plaketten im Kopf – vom Server gezählt, nur über Sichtbares. */
const statusCounts = computed(() =>
  Object.entries(block.value.counts).filter(([, n]) => n > 0))

/**
 * Abteilungen, in denen ich Mitglied bin, für die aber gerade nichts vorliegt.
 * Dezent anzeigen: „nichts zu tun" ist eine andere Aussage als „ich bin nicht
 * zuständig", und nur die erste ist beruhigend. BEWUSST dieselbe Quelle wie
 * die Abschnitte (abteilungsGruppen) – eine eigene Zähl-Logik hatte hier
 * „nichts zu tun" behauptet, während derselbe Auftrag oben in der Liste stand.
 */
const leereAbteilungen = computed(() =>
  abteilungsGruppen.value.filter((g) => !g.zeilen.length))

/** Die Zeilen-Obergrenze ist erreicht – dann ist die Arbeitsliste unvollständig. */
const listeAbgeschnitten = computed(() => rowsTotal.value > rows.value.length)

// ── Aktionen ──────────────────────────────────────────────────────────────────

function open(z: Zeile) {
  // Lesen ist der STANDARD der Detailansicht (auch ganz ohne Parameter). Die
  // Arbeits-Reiter („Mir zugewiesen", „Meine Abteilungen") springen direkt in
  // die Bearbeitung, die Beobachtungs-Reiter benennen das Lesen explizit –
  // Rechte vergibt der Parameter nicht (abilities entscheiden, Server prüft).
  const arbeit = activeTab.value === 'assigned' || activeTab.value === 'departments'
  router.push(`/prozess-auftraege/${z.id}?ansicht=${arbeit ? 'bearbeiten' : 'lesen'}`)
}

// ── Laden ─────────────────────────────────────────────────────────────────────

async function ladeDashboard() {
  try {
    const res = await client.get<{
      data: { process?: ProcessBlock; my_departments?: DepartmentRef[] }
    }>('/dashboard')
    const d = res.data.data
    block.value = {
      my:       d.process?.my ?? [],
      involved: d.process?.involved ?? [],
      watched: d.process?.watched ?? [],
      counts:   d.process?.counts ?? {},
    }
    myDepartments.value = d.my_departments ?? []
  } catch (e) {
    blockError.value = errorMessage(e, 'Übersicht konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

async function ladeAuftraege() {
  try {
    const res = await listTickets({ limit: ROWS_LIMIT })
    rows.value = res.items
    rowsTotal.value = res.total
  } catch (e) {
    rowsError.value = errorMessage(e, 'Arbeitslisten konnten nicht geladen werden')
  } finally {
    rowsLoading.value = false
  }
}

onMounted(async () => {
  // Parallel: die beiden Quellen hängen nicht voneinander ab.
  await Promise.all([ladeDashboard(), ladeAuftraege()])
  // Auf den Reiter springen, in dem tatsächlich Arbeit liegt.
  if (countAssigned.value > 0) activeTab.value = 'assigned'
  else if (countDepartments.value > 0) activeTab.value = 'departments'
  else if (countWatched.value > 0) activeTab.value = 'watched'
  else if (countInvolved.value > 0) activeTab.value = 'involved'
})
</script>

<template>
  <AppLayout title="Übersicht">

    <div v-if="loading && rowsLoading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else class="space-y-6">

      <!-- ── Kopf ── -->
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
            Willkommen zurück,
            <span class="text-[#3EAAB8]">{{ auth.user?.displayName }}</span> 👋
          </h1>
          <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            <template v-if="offeneAufgaben > 0">
              Du hast <strong class="text-gray-700 dark:text-gray-200">{{ offeneAufgaben }}</strong>
              offene Aufgaben.
            </template>
            <template v-else>Alles erledigt – keine offenen Aufgaben.</template>
          </p>
        </div>
        <!-- Kein Anlege-Knopf hier: Neues anlegen läuft über die Sidebar. -->
      </div>

      <!-- Ladefehler getrennt melden: fällt eine Quelle aus, bleibt die andere nutzbar -->
      <div v-if="blockError || rowsError" class="space-y-2">
        <p v-if="rowsError"
           class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                  dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          {{ rowsError }} – „Mir zugewiesen“ und „Meine Abteilungen“ sind unvollständig.
        </p>
        <p v-if="blockError"
           class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                  dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          {{ blockError }} – „Beobachtet“ und „Beteiligt“ sind unvollständig.
        </p>
      </div>

      <!-- ── Kacheln ── -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button @click="selectTab('assigned')" class="stat" :class="activeTab === 'assigned' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
            </span>
            <span class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ countAssigned }}</span>
          </div>
          <p class="stat-label inline-flex items-center gap-1">
            Mir zugewiesen
            <span class="hint" @click.stop>
              <svg class="hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/><line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/></svg>
              <span class="bubble">Aufträge, die aktuell dir persönlich zur Bearbeitung zugewiesen sind.</span>
            </span>
          </p>
        </button>

        <button @click="selectTab('departments')" class="stat" :class="activeTab === 'departments' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
            </span>
            <span class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ countDepartments }}</span>
          </div>
          <p class="stat-label inline-flex items-center gap-1">
            Meine Abteilungen
            <span class="hint" @click.stop>
              <svg class="hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/><line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/></svg>
              <span class="bubble">Aufträge, die aktuell einer deiner Fachabteilungen vorliegen – zur Bearbeitung oder Durchführung.</span>
            </span>
          </p>
        </button>

        <button @click="selectTab('watched')" class="stat" :class="activeTab === 'watched' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
            </span>
            <span class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ countWatched }}</span>
          </div>
          <p class="stat-label inline-flex items-center gap-1">
            Beobachtet
            <span class="hint" @click.stop>
              <svg class="hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/><line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/></svg>
              <span class="bubble">Aktive Aufträge, die du beobachtest. Als Ersteller bist du automatisch Beobachter. Du bekommst dafür keine Mails – du kannst den Auftrag öffnen und den aktuellen Bearbeitungsstand sehen.</span>
            </span>
          </p>
        </button>

        <button @click="selectTab('involved')" class="stat" :class="activeTab === 'involved' ? 'stat-on' : ''">
          <div class="flex items-center justify-between">
            <span class="stat-icon bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg>
            </span>
            <span class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ countInvolved }}</span>
          </div>
          <p class="stat-label inline-flex items-center gap-1">
            Beteiligt
            <span class="hint" @click.stop>
              <svg class="hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/><line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/></svg>
              <span class="bubble">Aktive Aufträge anderer, die du sehen darfst – weil du zuständig bist oder Aufsichtsrecht hast. Beobachtete stehen in ihrer eigenen Kachel.</span>
            </span>
          </p>
        </button>
      </div>

      <!-- ── Liste ── -->
      <div>
        <!-- Ergebnisse -->
        <div class="bg-gray-50 dark:bg-[#1A2130] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl overflow-hidden">

          <!-- Keine Ergebnis-Zahl: die steht schon groß in den Kacheln. Nur die
               Status-Verteilung über ALLE für mich sichtbaren Aufträge. -->
          <div v-if="statusCounts.length"
               class="px-5 py-2 flex items-center justify-end gap-1.5 flex-wrap
                      border-b border-gray-100 dark:border-white/[0.04]">
            <span v-for="[st, n] in statusCounts" :key="st"
                  class="text-xs font-medium px-2.5 py-1 rounded-full" :class="statusClass(st)">
              {{ statusLabel(st) }} · {{ n }}
            </span>
          </div>

          <ul class="divide-y divide-gray-100 dark:divide-white/[0.06] max-h-[560px] overflow-auto">
            <!-- EIN Zeilen-Markup für alle Reiter; der Abteilungs-Reiter streut
                 Abschnitts-Köpfe ein. Die Köpfe kleben beim Scrollen oben – bei
                 hunderten Aufträgen bleibt so erkennbar, in welcher Abteilung
                 man gerade liest. -->
            <template v-for="el in anzeige" :key="el.key">
              <li v-if="el.art === 'kopf'"
                  @click="abschnittUmklappen(el.id)"
                  class="sticky top-0 z-10 px-5 py-2 bg-gray-50 dark:bg-[#1A2130]
                         border-b border-gray-100 dark:border-white/[0.04]
                         flex items-center gap-2 cursor-pointer select-none
                         hover:bg-gray-100/70 dark:hover:bg-white/[0.04] transition">
                <svg class="w-3.5 h-3.5 text-gray-400 transition-transform"
                     :class="el.zu ? '-rotate-90' : ''"
                     viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
                <span class="text-[11px] font-semibold uppercase tracking-wider
                             text-purple-600 dark:text-purple-300">{{ el.name }}</span>
                <span class="text-[11px] text-gray-400">
                  · {{ el.anzahl }} {{ el.anzahl === 1 ? 'Auftrag' : 'Aufträge' }}
                </span>
              </li>
              <li v-else @click="open(el.z)" class="row group">
                <div class="flex items-start gap-3.5 min-w-0">
                  <div class="w-2 h-2 rounded-full flex-shrink-0 mt-1.5" :class="dotClass(el.z.status)" />
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#3EAAB8] transition-colors">
                      {{ el.z.title }} <span class="text-gray-400 font-normal text-xs">#{{ el.z.id }}</span>
                    </p>
                    <p class="text-xs text-gray-400 mt-0.5">
                      {{ el.z.process_key }} · {{ fmtDay(el.z.created_at) }}
                      <template v-if="el.z.phase_label"> · {{ el.z.phase_label }}</template>
                      <template v-if="el.z.depts"> · {{ el.z.depts.text }}</template>
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2.5 flex-shrink-0 ml-4">
                  <span v-if="el.z.badge"
                        class="hidden sm:inline text-[10px] font-semibold px-1.5 py-0.5 rounded"
                        :class="el.z.badge.class">{{ el.z.badge.text }}</span>
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="statusClass(el.z.status)">
                    {{ statusLabel(el.z.status) }}
                  </span>
                  <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </li>
            </template>

            <li v-if="anzeige.length === 0" class="empty">
              <template v-if="activeTab === 'assigned'">Keine dir persönlich zugewiesenen Aufträge.</template>
              <template v-else-if="activeTab === 'departments'">Keine Aufträge für deine Fachabteilungen.</template>
              <template v-else-if="activeTab === 'watched'">Du beobachtest gerade keinen Auftrag.</template>
              <template v-else>Keine Aufträge, an denen du beteiligt bist.</template>
            </li>
          </ul>

          <!-- Mitgliedschafts-Info: Abteilungen ohne aktuelle Aufgabe -->
          <div v-if="activeTab === 'departments' && leereAbteilungen.length"
               class="px-5 py-3.5 border-t border-gray-100 dark:border-white/[0.04]">
            <p class="text-[11px] uppercase tracking-wider text-gray-400 mb-2">
              Mitglied · derzeit keine offenen Aufträge
            </p>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="d in leereAbteilungen" :key="d.id"
                    class="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full
                           bg-gray-100/70 dark:bg-white/[0.05] text-gray-500 dark:text-gray-400">
                <span class="w-1.5 h-1.5 rounded-full bg-gray-300 dark:bg-white/20" />
                {{ d.name }}
              </span>
            </div>
          </div>

          <!-- Ehrlichkeits-Hinweis: die Arbeitslisten lesen nur die erste Seite.
               Der Link zur Auftragsliste nur für die Aufsichts-Rollen – für alle
               anderen ist die Seite gesperrt (Route-Guard). -->
          <div v-if="listeAbgeschnitten && (activeTab === 'assigned' || activeTab === 'departments')"
               class="px-5 py-3 border-t border-gray-100 dark:border-white/[0.04]
                      text-xs text-gray-500 dark:text-gray-400">
            Es gibt mehr als {{ rows.length }} sichtbare Aufträge ({{ rowsTotal }}).
            Diese Liste zeigt nur die neuesten<template v-if="hatAufsicht"> – die
            vollständige Suche steht unter
            <button @click="router.push('/auftraege')" class="text-[#3EAAB8] hover:underline">
              Alle Aufträge</button></template>.
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../style.css";

.stat {
  @apply relative bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
         rounded-2xl p-4 text-left transition-all duration-200
         hover:z-30 hover:shadow-md hover:-translate-y-0.5 hover:border-gray-300 dark:hover:border-white/20;
}
.stat-on {
  @apply ring-2 ring-[#3EAAB8]/50 border-[#3EAAB8]/40 shadow-sm
         bg-[#3EAAB8]/[0.05] dark:bg-[#3EAAB8]/[0.08];
}
.stat-icon { @apply w-8 h-8 rounded-xl flex items-center justify-center; }
/* kräftigere Icon-Striche */
.stat-icon svg { stroke-width: 2.3px; }
.stat-label { @apply text-[13px] font-semibold text-gray-700 dark:text-gray-200 mt-2.5; }

.fi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         placeholder-gray-400 px-3.5 py-2 text-sm
         focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}

.row {
  @apply flex items-start justify-between px-5 py-4 cursor-pointer
         hover:bg-white/60 dark:hover:bg-[#263040] transition;
}

.empty { @apply px-5 py-14 text-center text-sm text-gray-400 italic; }

/* Info-Icon mit Hover-Tooltip auf den Kacheln.
   Die Bubble wird relativ zur Karte (.stat = relative) zentriert und darunter
   gelegt – so läuft sie auch bei der rechten Karte nicht über den Rand. */
.hint { @apply inline-flex items-center cursor-help; }
.hint-icon { @apply w-[18px] h-[18px] text-gray-300 dark:text-gray-600 transition-colors; }
.hint:hover .hint-icon { @apply text-gray-500 dark:text-gray-300; }
.bubble {
  @apply pointer-events-none absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 w-44 sm:w-56
         rounded-lg bg-gray-900 text-gray-100 text-[11px] leading-snug px-3 py-2
         opacity-0 transition-opacity duration-150 normal-case font-normal text-left shadow-lg;
}
.hint:hover .bubble { @apply opacity-100; }
</style>
