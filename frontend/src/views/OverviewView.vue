<script setup lang="ts">
/**
 * Übersicht – die Startseite. EINE Liste für ALLE Aufträge.
 *
 * Zusammengelegt aus zwei Ansichten: der Arbeitslisten-Startseite (vier Kacheln)
 * und der eigenen Liste unter /prozess-auftraege. Die Arbeitslisten sind nicht
 * verschwunden, sie sind jetzt die SICHTEN dieser Liste (Kacheln oben, siehe
 * components/overview/OverviewScopeTiles.vue).
 *
 * DREI QUELLEN, jede mit einem Grund:
 *
 *  1. `GET /process-tickets` – die Aufträge selbst. Nur diese Zeilen tragen
 *     `responsibility` mit dem LIVE-Stand der Fachabteilungen; ohne sie lässt
 *     sich „wartet auf MEINE Abteilung" nicht beantworten (lib/processDepartments).
 *     Der Server filtert selbst, wer was sehen darf – hier wird nichts nachgebaut.
 *  2. `GET /dashboard` – NUR `my_departments`: in welchen Fachabteilungen bin
 *     ich? Das steht in keiner Auftragszeile und lässt sich hier nicht herleiten
 *     (das Frontend kennt die Gruppen-Mitgliedschaft nicht).
 *  3. `GET /processes` + Auswahl-Quellen – Namen und Symbole zu den IDs, die die
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
import OverviewScopeTiles from '@/components/overview/OverviewScopeTiles.vue'
import OverviewTable from '@/components/overview/OverviewTable.vue'
import { client } from '@/api/client'
import { listTickets } from '@/api/processTickets'
import { listProcesses } from '@/api/processes'
import { useAuthStore } from '@/stores/authStore'
import { BASIS_TICKET_PATH } from '@/lib/basisTicket'
import { isDepartmentPending } from '@/lib/processDepartments'
import { errorMessage } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { buildLookup, toOverviewRows } from '@/lib/overviewRow'
import {
  applyScope, CLIENT_SIDE_LABEL, defaultStatuses, filterByStatus, isWindowTruncated,
  OVERVIEW_STATUSES, pageCount, pageSlice, parseTicketRef, planQuery, SCOPE_EMPTY,
  SCOPE_LABEL, SERVER_SORT_DIR, SERVER_SORT_KEY, sortTickets,
  type OverviewScope, type OverviewSortKey, type ScopeContext, type SortDir,
} from '@/lib/overviewQuery'
import type { OptionSources, ProcessOut, ProcessTicketOut } from '@/types/process'

const router = useRouter()
const auth = useAuthStore()

/** Zeilen je Seite (wie in der Übersicht vor dem Umbau). */
const PAGE_SIZE = 25
/** Obergrenze des Endpunkts (limit ≤ 200) – mehr gibt es nicht in einem Rutsch. */
const SCAN_LIMIT = 200

// ── Filter- und Sortier-Zustand ───────────────────────────────────────────────

const scope = ref<OverviewScope>('all')
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
    scope: scope.value, statuses: statuses.value, q: suche.value,
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

/**
 * Arbeitsfenster für die Kachel-Zähler: die neuesten Aufträge OHNE Filter.
 * Eigenes Fenster, weil die Frage „wartet etwas auf mich?" sich nicht ändern
 * darf, nur weil unten ein Status abgewählt oder ein Prozess gewählt ist.
 */
const fenster = ref<ProcessTicketOut[]>([])
const fensterTotal = ref(0)
const fensterLoading = ref(true)
const fensterError = ref<string | null>(null)

const meineFachabteilungen = ref<{ id: string; name: string }[]>([])
const abteilungenError = ref<string | null>(null)

const katalog = ref<ProcessOut[]>([])
const quellen = ref<OptionSources>(emptySources())

/**
 * Ist das Listen-Fenster selbst das ungefilterte Arbeitsfenster? Dann sind die
 * Kachel-Zähler daraus zu holen und der zweite Aufruf entfällt – das ist der
 * Normalfall beim Aufruf der Startseite.
 */
const listeIstArbeitsfenster = computed(() => {
  const p = plan.value
  return p.mode === 'scan' && !p.params.status && !p.params.process_key && !p.params.q
})
const arbeitsZeilen = computed(() => (
  listeIstArbeitsfenster.value ? liste.value : fenster.value))
const arbeitsTotal = computed(() => (
  listeIstArbeitsfenster.value ? listeTotal.value : fensterTotal.value))
const arbeitsLoading = computed(() => (
  listeIstArbeitsfenster.value ? listeLoading.value : fensterLoading.value))
/** Das Arbeitsfenster reicht nicht über alle sichtbaren Aufträge → Zähler sind Untergrenzen. */
const arbeitsAbgeschnitten = computed(() => arbeitsTotal.value > arbeitsZeilen.value.length)

// ── Wer fragt? ────────────────────────────────────────────────────────────────

const ctx = computed<ScopeContext>(() => ({
  userId: auth.user?.id ?? null,
  groupIds: meineFachabteilungen.value.map((d) => d.id),
}))

// ── Zähler der Kacheln ────────────────────────────────────────────────────────

const counts = computed<Record<OverviewScope, number>>(() => {
  const rows = arbeitsZeilen.value
  return {
    // „Alle": bei vollständigem Fenster die Serverzahl, sonst das Geladene –
    // die Kachel schreibt dann ein „+" dahinter, statt Vollständigkeit zu behaupten.
    all: arbeitsAbgeschnitten.value ? rows.length : arbeitsTotal.value,
    assigned: applyScope(rows, 'assigned', ctx.value).length,
    departments: applyScope(rows, 'departments', ctx.value).length,
    created: applyScope(rows, 'created', ctx.value).length,
    involved: applyScope(rows, 'involved', ctx.value).length,
  }
})

const offeneAufgaben = computed(() => counts.value.assigned + counts.value.departments)

/**
 * Meine Fachabteilungen, für die gerade nichts vorliegt. „Nichts zu tun" ist
 * eine andere Aussage als „ich bin nicht zuständig" – nur die erste beruhigt.
 *
 * Gezählt wird je ABTEILUNG, nicht je Auftrag: dass ein Auftrag noch offen ist,
 * heißt nicht, dass MEINE Abteilung dort noch etwas zu quittieren hat – sie kann
 * längst abgeschlossen haben, während eine andere noch fehlt. Deshalb derselbe
 * Maßstab wie in der Sicht „Meine Abteilungen" (`isDepartmentPending`).
 */
const leereAbteilungen = computed(() => {
  const wartend = new Set(
    applyScope(arbeitsZeilen.value, 'departments', ctx.value).flatMap((t) => {
      const r = t.responsibility
      if (!r || r.kind !== 'departments') return []
      return (r.departments ?? []).filter(isDepartmentPending).map((d) => d.group)
    }),
  )
  return meineFachabteilungen.value.filter((d) => !wartend.has(d.id))
})

// ── Anzeige-Zeilen ────────────────────────────────────────────────────────────

const lookup = computed(() => buildLookup({
  catalog: katalog.value, groups: quellen.value.groups, users: quellen.value.users,
}))

/** Sicht + Status clientseitig nachziehen, dann sortieren (siehe lib/overviewQuery). */
const gefiltert = computed(() => {
  let rows: ProcessTicketOut[] = liste.value
  if (scope.value !== 'all') rows = applyScope(rows, scope.value, ctx.value)
  rows = filterByStatus(rows, statuses.value)
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
 * Zurück in den Server-Modus: alle Status, Sicht „Alle", Server-Sortierung.
 * Danach blättert der Server – die Liste ist vollständig.
 */
function vollstaendigBlaettern() {
  scope.value = 'all'
  statuses.value = [...OVERVIEW_STATUSES]
  sortKey.value = SERVER_SORT_KEY
  sortDir.value = SERVER_SORT_DIR
}

function oeffnen(id: number) {
  // Admins öffnen aus der Auftragsliste die Admin-Ansicht (Leseansicht plus
  // Reparatur-Werkzeuge); alle anderen die normale Leseansicht. Der Parameter
  // vergibt KEINE Rechte – jeden Admin-Endpunkt prüft der Server selbst.
  router.push(auth.isAdmin ? `/prozess-auftraege/${id}?ansicht=admin`
                           : `/prozess-auftraege/${id}`)
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

let arbeitsfensterGeladen = false
/** Nur laden, wenn das Listen-Fenster die Zähler nicht mit trägt. */
async function ladeArbeitsfenster() {
  if (listeIstArbeitsfenster.value || arbeitsfensterGeladen) return
  arbeitsfensterGeladen = true
  fensterLoading.value = true
  fensterError.value = null
  try {
    const res = await listTickets({ limit: SCAN_LIMIT })
    fenster.value = res.items
    fensterTotal.value = res.total
  } catch (e) {
    arbeitsfensterGeladen = false
    fensterError.value = errorMessage(e, 'Arbeitslisten konnten nicht geladen werden')
  } finally {
    fensterLoading.value = false
  }
}

async function ladeFachabteilungen() {
  abteilungenError.value = null
  try {
    const res = await client.get<{ data: { my_departments?: { id: string; name: string }[] } }>(
      '/dashboard')
    meineFachabteilungen.value = res.data.data.my_departments ?? []
  } catch (e) {
    abteilungenError.value = errorMessage(e, 'Fachabteilungen konnten nicht geladen werden')
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

async function allesNeuLaden() {
  arbeitsfensterGeladen = false
  await Promise.all([ladeListe(), ladeArbeitsfenster(), ladeFachabteilungen()])
}

// REIHENFOLGE BEACHTEN: dieser Beobachter wird VOR dem Anfrage-Beobachter
// angelegt und läuft deshalb zuerst. Sonst lädt ein Filterwechsel zweimal –
// einmal mit der alten Seitenzahl und gleich danach mit der zurückgesetzten.
watch([scope, statuses, suche, processKey, sortKey, sortDir], () => { page.value = 1 })

// Nur wenn sich die ANFRAGE ändert, wird geladen. Im Scan-Modus blättert und
// sortiert der Client im geladenen Fenster – das braucht keinen neuen Aufruf.
watch(() => JSON.stringify(plan.value.params), ladeListe)
watch(listeIstArbeitsfenster, () => { ladeArbeitsfenster() })

// Entprellte Suche: sonst je Tastendruck ein Aufruf.
let tippTimer: ReturnType<typeof setTimeout> | null = null
watch(sucheEingabe, (v) => {
  if (tippTimer) clearTimeout(tippTimer)
  tippTimer = setTimeout(() => { suche.value = v }, 250)
})

// Nach dem Laden kann die Seite hinter dem Ergebnis liegen (z. B. weniger Treffer).
watch(seitenAnzahl, (n) => { if (page.value > n) page.value = n })

onMounted(async () => {
  await Promise.all([ladeListe(), ladeFachabteilungen(), ladeNamen()])
  // Erst danach: ob ein eigenes Arbeitsfenster nötig ist, hängt am Plan.
  await ladeArbeitsfenster()
})
</script>

<template>
  <AppLayout title="Übersicht">
    <div class="space-y-5">

      <!-- ── Kopf ── -->
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
            Willkommen zurück,
            <span class="text-[#3EAAB8]">{{ auth.user?.displayName }}</span> 👋
          </h1>
          <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            <template v-if="arbeitsLoading">Aufträge werden geladen…</template>
            <template v-else-if="offeneAufgaben > 0">
              Du hast <strong class="text-gray-700 dark:text-gray-200">{{ offeneAufgaben }}</strong>
              offene {{ offeneAufgaben === 1 ? 'Aufgabe' : 'Aufgaben' }}.
            </template>
            <template v-else>Alles erledigt – keine offenen Aufgaben.</template>
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button @click="router.push('/prozess-auftraege/neu')"
                  class="px-4 py-2 rounded-xl text-sm font-medium text-white
                         bg-[#3EAAB8] hover:bg-[#2B7D89] transition">
            + Neues Prozess-Ticket
          </button>
          <button @click="router.push(BASIS_TICKET_PATH)"
                  class="px-4 py-2 rounded-xl text-sm font-medium
                         border border-gray-200 dark:border-white/10
                         text-gray-600 dark:text-gray-300
                         hover:bg-gray-50 dark:hover:bg-white/5 transition">
            + Neues Ticket
          </button>
        </div>
      </div>

      <!-- Ladefehler getrennt melden: fällt eine Quelle aus, bleibt der Rest nutzbar -->
      <div v-if="listeError || fensterError || abteilungenError" class="space-y-2">
        <p v-if="listeError" class="warnbox">{{ listeError }}</p>
        <p v-if="fensterError" class="warnbox">
          {{ fensterError }} – die Zähler der Kacheln fehlen.
        </p>
        <p v-if="abteilungenError" class="warnbox">
          {{ abteilungenError }} – „Meine Abteilungen" bleibt leer.
        </p>
      </div>

      <!-- ── Sichten ── -->
      <OverviewScopeTiles :active="scope" :counts="counts" :loading="arbeitsLoading"
                          :truncated="arbeitsAbgeschnitten"
                          @select="scope = $event" />

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
          <button @click="allesNeuLaden" title="Neu laden"
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
          {{ SCOPE_LABEL[scope] }}:
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
                     :empty-text="SCOPE_EMPTY[scope]"
                     @open="oeffnen" @sort="setSort" />

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

      <!-- Mitgliedschafts-Info: Abteilungen ohne aktuelle Aufgabe -->
      <div v-if="scope === 'departments' && leereAbteilungen.length"
           class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                  rounded-2xl px-5 py-3.5">
        <p class="text-[11px] uppercase tracking-wider text-gray-400 mb-2">
          Mitglied · derzeit nichts zu quittieren
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
