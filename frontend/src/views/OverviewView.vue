<script setup lang="ts">
/**
 * Übersicht – die Startseite. EINE Liste für ALLE Aufträge.
 *
 * Aufsichts-Liste über ALLE Aufträge (Route nur für viewer/manager/admin – der
 * Server liefert diesen Rollen die ungefilterte Liste). Die persönlichen
 * Arbeitslisten-Sichten (Kacheln) sind bewusst WEG: „was liegt bei MIR an?"
 * beantwortet die Startseite (/dashboard), hier geht es um alles.
 *
 * ZWEI QUELLEN, jede mit einem Grund:
 *
 *  1. `GET /process-tickets` – die Aufträge selbst (mit `responsibility` für
 *     die Spalte „Zuständig"). Der Server filtert selbst, wer was sehen darf –
 *     hier wird nichts nachgebaut.
 *  2. `GET /processes` + Auswahl-Quellen – Namen und Symbole zu den IDs, die die
 *     Liste liefert (Prozess-Key, Gruppen-/Personen-IDs).
 *
 * Alle Aufrufe sind unabhängig abgesichert: fällt einer aus, bleibt der Rest
 * nutzbar; fehlende Namen zeigen den Rohwert.
 *
 * WAS DER SERVER FILTERT UND WAS NICHT, entscheidet lib/overviewQuery.ts. Sobald
 * die Oberfläche mitfiltern muss (mehrere Status, eine Arbeitsliste, eine andere
 * Sortierung), ist die Liste nur noch das geladene FENSTER – und sagt das auch
 * (Ehrlichkeits-Hinweis unter der Tabelle).
 *
 * KEINE Priorität: nicht als Spalte, nicht als Filter, nicht in der Sortierung –
 * sie ist überall ausgeblendet, bis geklärt ist, wie sie sinnvoll genutzt wird.
 * Feld, API und Typen bleiben unverändert.
 *
 * KEINE Sammel-Aktionen (früher „Archivieren"/„Löschen" über Kästchen): dafür
 * gibt es keinen Sammel-Endpunkt mehr, und der Zwangs-Abschluss verlangt je
 * Auftrag eine Begründung. Beide Notfall-Eingriffe stehen in der Detailansicht.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import OverviewTable from '@/components/overview/OverviewTable.vue'
import { archiveTicket, listTickets } from '@/api/processTickets'
import { useToast } from '@/composables/useToast'
import { listProcesses } from '@/api/processes'
import { useAuthStore } from '@/stores/authStore'
import { errorMessage } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { buildLookup, toOverviewRows } from '@/lib/overviewRow'
import {
  CLIENT_SIDE_LABEL, defaultStatuses, filterByStatus, isWindowTruncated,
  OVERVIEW_STATUSES, pageCount, pageSlice, parseTicketRef, planQuery, SCOPE_EMPTY,
  SERVER_SORT_DIR, SERVER_SORT_KEY, sortTickets,
  type OverviewSortKey, type SortDir,
} from '@/lib/overviewQuery'
import type { OptionSources, ProcessOut, ProcessTicketOut } from '@/types/process'

const router = useRouter()
const auth = useAuthStore()

/** Zeilen je Seite (wie in der Übersicht vor dem Umbau). */
const PAGE_SIZE = 25
/** Obergrenze des Endpunkts (limit ≤ 200) – mehr gibt es nicht in einem Rutsch. */
const SCAN_LIMIT = 200

// ── Filter- und Sortier-Zustand ───────────────────────────────────────────────
// Keine Sichten-Kacheln mehr: die Seite zeigt IMMER alle Aufträge („scope all"),
// die persönlichen Arbeitslisten wohnen auf der Startseite.

const statuses = ref<string[]>(defaultStatuses())
/** Eingabe der Suche; an den Server geht der entprellte Wert. */
const sucheEingabe = ref('')
const suche = ref('')
const processKey = ref('')
const sortKey = ref<OverviewSortKey>(SERVER_SORT_KEY)
const sortDir = ref<SortDir>(SERVER_SORT_DIR)
const page = ref(1)

const plan = computed(() => planQuery(
  {
    scope: 'all', statuses: statuses.value, q: suche.value,
    processKey: processKey.value, sortKey: sortKey.value, sortDir: sortDir.value,
  },
  { page: page.value, pageSize: PAGE_SIZE, scanLimit: SCAN_LIMIT },
))

const istServerModus = computed(() => plan.value.mode === 'server')

// ── Zustand der Ladevorgänge ──────────────────────────────────────────────────

const liste = ref<ProcessTicketOut[]>([])
const listeTotal = ref(0)
const listeLoading = ref(true)
const listeError = ref<string | null>(null)

const katalog = ref<ProcessOut[]>([])
const quellen = ref<OptionSources>(emptySources())

// ── Anzeige-Zeilen ────────────────────────────────────────────────────────────

const lookup = computed(() => buildLookup({
  catalog: katalog.value, groups: quellen.value.groups, users: quellen.value.users,
}))

/** Status clientseitig nachziehen, dann sortieren (siehe lib/overviewQuery). */
const gefiltert = computed(() => {
  const rows = filterByStatus(liste.value, statuses.value)
  return sortTickets(rows, sortKey.value, sortDir.value)
})

/** Im Server-Modus ist die Antwort schon die Seite; im Scan-Modus blättert der Client. */
const seitenZeilen = computed(() => (
  istServerModus.value ? gefiltert.value : pageSlice(gefiltert.value, page.value, PAGE_SIZE)))
const zeilen = computed(() => toOverviewRows(seitenZeilen.value, lookup.value))

/**
 * Im Server-Modus ist `meta.total` die Zahl des Servers. Ohne Aufsichtsrechte ist
 * sie eine OBERGRENZE: der Server zieht nur die Zeilen ab, die er auf der
 * geladenen Seite wegen fehlender Sichtbarkeit entfernt hat. Die letzte Seite
 * kann deshalb leer bleiben – besser als eine erfundene, zu kleine Zahl.
 */
const ergebnisAnzahl = computed(() => (
  istServerModus.value ? listeTotal.value : gefiltert.value.length))
const seitenAnzahl = computed(() => pageCount(ergebnisAnzahl.value, PAGE_SIZE))

/** Die Liste zeigt NICHT das Gesamtergebnis – das muss dranstehen. */
const abgeschnitten = computed(() => isWindowTruncated(plan.value, listeTotal.value, liste.value.length))
const clientGruende = computed(() => plan.value.clientSide.map((r) => CLIENT_SIDE_LABEL[r]))

const idTreffer = computed(() => parseTicketRef(sucheEingabe.value))

const statusOptionen = computed(() => OVERVIEW_STATUSES.map(
  (s) => ({ key: s, label: STATUS_LABEL[s] ?? s })))

// ── Bedienung ─────────────────────────────────────────────────────────────────

function toggleStatus(s: string) {
  statuses.value = statuses.value.includes(s)
    ? statuses.value.filter((x) => x !== s)
    : [...statuses.value, s]
}

function setSort(key: OverviewSortKey) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    // Datum und ID zuerst absteigend (das Neueste oben), Text aufsteigend.
    sortDir.value = key === 'title' || key === 'owner' ? 'asc' : 'desc'
  }
}

function zuruecksetzen() {
  statuses.value = defaultStatuses()
  sucheEingabe.value = ''
  suche.value = ''
  processKey.value = ''
  sortKey.value = SERVER_SORT_KEY
  sortDir.value = SERVER_SORT_DIR
}

/**
 * Zurück in den Server-Modus: alle Status, Server-Sortierung.
 * Danach blättert der Server – die Liste ist vollständig.
 */
function vollstaendigBlaettern() {
  statuses.value = [...OVERVIEW_STATUSES]
  sortKey.value = SERVER_SORT_KEY
  sortDir.value = SERVER_SORT_DIR
}

function oeffnen(id: number) {
  // Admins öffnen aus der Auftragsliste die Admin-Ansicht (Leseansicht plus
  // Reparatur-Werkzeuge); viewer und manager die normale Leseansicht. Der
  // Parameter vergibt KEINE Rechte – jeden Admin-Endpunkt prüft der Server.
  router.push(auth.isAdmin ? `/prozess-auftraege/${id}?ansicht=admin`
                           : `/prozess-auftraege/${id}`)
}

// ── Archivieren aus der Liste (Manager + Admin) ───────────────────────────────
// Die einzige Schreibaktion der Manager-Rolle (Alt-System-Regel). Verbindlich
// prüft der Server (:archive erlaubt manage/admin, sonst 403).

const { showToast } = useToast()
const darfArchivieren = computed(() => auth.canManage || auth.isAdmin)

async function archivieren(id: number) {
  const grund = prompt(`Auftrag #${id} zwangsweise abschließen – warum? `
    + '(Pflicht, steht im Verlauf)')
  if (grund === null) return
  if (!grund.trim()) { showToast('Ohne Begründung kein Zwangsabschluss', false); return }
  try {
    await archiveTicket(id, grund.trim())
    showToast('Auftrag archiviert')
    await ladeListe()
  } catch (e) {
    showToast(errorMessage(e, 'Archivieren fehlgeschlagen'), false)
  }
}

// ── Laden ─────────────────────────────────────────────────────────────────────

let listeReq = 0
async function ladeListe() {
  const meine = ++listeReq
  listeLoading.value = true
  listeError.value = null
  try {
    const res = await listTickets(plan.value.params)
    if (meine !== listeReq) return      // überholte Antwort verwerfen
    liste.value = res.items
    listeTotal.value = res.total
  } catch (e) {
    if (meine !== listeReq) return
    listeError.value = errorMessage(e, 'Aufträge konnten nicht geladen werden')
    liste.value = []
    listeTotal.value = 0
  } finally {
    if (meine === listeReq) listeLoading.value = false
  }
}

/** Namen zu den IDs. Fehlschläge sind nicht fatal – dann steht der Rohwert da. */
async function ladeNamen() {
  try {
    katalog.value = await listProcesses()
  } catch {
    /* Prozess-Filter bleibt leer, die Liste zeigt den Key */
  }
  // Fachabteilungen und Personen für die Spalte „Zuständig". Ohne Adminrechte
  // ist /settings/groups gesperrt – dann der öffentliche Endpunkt.
  quellen.value = await loadOptionSources(auth.isAdmin)
}

// REIHENFOLGE BEACHTEN: dieser Beobachter wird VOR dem Anfrage-Beobachter
// angelegt und läuft deshalb zuerst. Sonst lädt ein Filterwechsel zweimal –
// einmal mit der alten Seitenzahl und gleich danach mit der zurückgesetzten.
watch([statuses, suche, processKey, sortKey, sortDir], () => { page.value = 1 })

// Nur wenn sich die ANFRAGE ändert, wird geladen. Im Scan-Modus blättert und
// sortiert der Client im geladenen Fenster – das braucht keinen neuen Aufruf.
watch(() => JSON.stringify(plan.value.params), ladeListe)

// Entprellte Suche: sonst je Tastendruck ein Aufruf.
let tippTimer: ReturnType<typeof setTimeout> | null = null
watch(sucheEingabe, (v) => {
  if (tippTimer) clearTimeout(tippTimer)
  tippTimer = setTimeout(() => { suche.value = v }, 250)
})

// Nach dem Laden kann die Seite hinter dem Ergebnis liegen (z. B. weniger Treffer).
watch(seitenAnzahl, (n) => { if (page.value > n) page.value = n })

onMounted(async () => {
  await Promise.all([ladeListe(), ladeNamen()])
})
</script>

<template>
  <AppLayout title="Übersicht">
    <div class="space-y-5">

      <!-- ── Kopf ── -->
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">Alle Aufträge</h1>
          <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            Sämtliche Aufträge im System – durchsuchen, filtern, blättern.
          </p>
        </div>
        <!-- Keine Anlege-Knöpfe hier: Neues anlegen läuft über die Sidebar. -->
      </div>

      <div v-if="listeError" class="space-y-2">
        <p class="warnbox">{{ listeError }}</p>
      </div>

      <!-- ── Filter ── -->
      <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                  rounded-2xl shadow-sm p-3.5 space-y-3">
        <!-- Status als Mehrfachauswahl (kein „Alle"-Knopf): aktive sind
             hervorgehoben, abwählen blendet aus. Sind alle aktiv, ist alles
             sichtbar – genau EIN aktiver Status filtert der Server selbst. -->
        <div class="flex flex-wrap items-center gap-2">
          <button v-for="s in statusOptionen" :key="s.key" @click="toggleStatus(s.key)"
                  class="px-3 py-1.5 rounded-xl text-sm font-medium border transition"
                  :class="statuses.includes(s.key)
                    ? 'bg-[#3EAAB8] text-white border-[#3EAAB8]'
                    : 'bg-white dark:bg-[#263040] border-gray-200 dark:border-white/10 text-gray-500 dark:text-gray-400 hover:border-[#3EAAB8]/40'">
            {{ s.label }}
          </button>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto] gap-2 items-center">
          <div class="relative">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
                 fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <!-- Der Server sucht ausschließlich im TITEL. Das steht so im
                 Platzhalter, statt einen unvollständigen Client-Filter über
                 Ersteller/Zuständig zu bauen, der nur das Fenster durchsucht. -->
            <input v-model="sucheEingabe" placeholder="Im Titel suchen…" class="fi !pl-10 w-full" />
          </div>
          <select v-model="processKey" class="fi">
            <option value="">Alle Prozesse</option>
            <option v-for="p in katalog" :key="p.key" :value="p.key">
              {{ p.icon ? p.icon + ' ' : '' }}{{ p.name }}
            </option>
          </select>
          <button @click="zuruecksetzen"
                  class="px-3 py-2 rounded-xl text-sm text-gray-500 dark:text-gray-400
                         border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 transition">
            Zurücksetzen
          </button>
          <button @click="ladeListe" title="Neu laden"
                  class="px-3 py-2 rounded-xl text-sm text-gray-500 dark:text-gray-400
                         border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 transition">
            ↻
          </button>
        </div>

        <!-- Nummern-Suche kann der Server nicht (er sucht im Titel) – deshalb
             der direkte Weg zum Auftrag, statt eines Filters, der nichts findet. -->
        <p v-if="idTreffer" class="text-sm text-gray-500 dark:text-gray-400">
          <button @click="oeffnen(idTreffer)" class="text-[#3EAAB8] hover:underline font-medium">
            Auftrag #{{ idTreffer }} öffnen
          </button>
          <span class="text-gray-400"> · die Suche selbst durchsucht nur Titel</span>
        </p>

        <p v-if="!statuses.length" class="text-sm text-amber-700 dark:text-amber-300">
          Kein Status ausgewählt – es wird nichts angezeigt. Wähle mindestens einen Status.
        </p>
      </div>

      <!-- ── Ergebnis-Zeile ── -->
      <div class="flex items-center justify-between gap-3 flex-wrap text-sm text-gray-400">
        <span>
          <strong class="text-gray-600 dark:text-gray-300">{{ ergebnisAnzahl }}</strong>
          {{ ergebnisAnzahl === 1 ? 'Auftrag' : 'Aufträge' }}
          <template v-if="seitenAnzahl > 1"> · Seite {{ page }} von {{ seitenAnzahl }}</template>
        </span>
        <!-- Nur wenn das geladene Fenster wirklich alles enthält (im Server-Modus
             immer, im Scan-Modus solange es nicht abgeschnitten ist). -->
        <span v-if="!abgeschnitten && !listeLoading" class="text-xs">Vollständiges Ergebnis</span>
      </div>

      <!-- ── Tabelle ── -->
      <OverviewTable :rows="zeilen" :sort-key="sortKey" :sort-dir="sortDir"
                     :loading="listeLoading && !liste.length"
                     :empty-text="SCOPE_EMPTY.all"
                     :can-archive="darfArchivieren"
                     @open="oeffnen" @sort="setSort" @archive="archivieren" />

      <!-- ── Ehrlichkeits-Hinweis: das ist NICHT das Gesamtergebnis ── -->
      <div v-if="abgeschnitten"
           class="rounded-2xl border border-amber-200 dark:border-amber-500/30
                  bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm
                  text-amber-800 dark:text-amber-200 space-y-1">
        <p>
          Es gibt mehr sichtbare Aufträge ({{ listeTotal }}) als hier geladen
          ({{ liste.length }}). Diese Liste zeigt die zuletzt geänderten –
          Filter und Sortierung wirken nur darauf.
        </p>
        <p class="text-xs">
          Grund: {{ clientGruende.join(', ') }} kann der Server nicht filtern.
          <button @click="vollstaendigBlaettern" class="underline font-medium">
            Vollständig blättern
          </button>
          (alle Status, Sicht „Alle Aufträge", Sortierung nach Änderung).
        </p>
      </div>

      <!-- ── Blättern ── -->
      <div v-if="seitenAnzahl > 1" class="flex items-center justify-between text-sm text-gray-400">
        <span>Seite {{ page }} von {{ seitenAnzahl }}</span>
        <div class="flex gap-2">
          <button @click="page = Math.max(1, page - 1)" :disabled="page <= 1"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">
            ← Zurück
          </button>
          <button @click="page = Math.min(seitenAnzahl, page + 1)" :disabled="page >= seitenAnzahl"
                  class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-40 transition">
            Weiter →
          </button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../style.css";

.fi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         placeholder-gray-400 px-3.5 py-2 text-sm
         focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}

.warnbox {
  @apply rounded-xl border border-amber-200 dark:border-amber-500/30
         bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm
         text-amber-800 dark:text-amber-200;
}
</style>
