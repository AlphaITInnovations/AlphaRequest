<script setup lang="ts">
/**
 * Übersicht aller Prozess-Definitionen inkl. Versionen.
 *
 * Besonderheit: Es gibt serverseitig keine Liste unveröffentlichter Prozesse.
 * `listProcesses()` liefert nur den veröffentlichten Katalog; alles Weitere
 * kommt aus dem lokalen Schlüssel-Verzeichnis (siehe processRegistry.ts).
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  createDraft, deleteVersion, exportVersion, listProcesses, listVersions, publishVersion,
  requestProcessDelete, setProcessActive,
} from '@/api/processes'
import { errorCode, errorMessage } from '@/lib/processErrors'
import {
  SYSTEM_PROCESS_BLOCKED, SYSTEM_PROCESS_HINT, isSystemProcess, isSystemReadonlyError,
} from '@/lib/processSystem'
import { forgetKey, loadKnownKeys, rememberKey } from '@/components/process/processRegistry'
import NewProcessModal from '@/components/process/NewProcessModal.vue'
import ImportProcessModal from '@/components/process/ImportProcessModal.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import type { ProcessOut } from '@/types/process'

const router = useRouter()
const auth = useAuthStore()
const { showToast } = useToast()

const rows     = ref<ProcessOut[]>([])
const versions = ref<Record<string, ProcessOut[]>>({})
const loading  = ref(false)
const expanded = ref<string | null>(null)
/** Kennung der laufenden Aktion, z. B. 'p:onboarding:2' – sperrt genau einen Button. */
const busy     = ref<string | null>(null)
const search   = ref('')

const newOpen    = ref(false)
const newMode    = ref<'create' | 'duplicate'>('create')
const newSource  = ref<string | null>(null)
const importOpen = ref(false)

/**
 * System-Prozess: das Merkmal kommt vom Server (`is_system`), nicht aus einer
 * Schlüssel-Liste hier. Die Zeile bietet dann keine schreibenden Aktionen an –
 * abgewiesen würden sie ohnehin (403 SYSTEM_PROCESS_READONLY), aber ein Knopf,
 * der nur Fehler produziert, ist eine Falle. Kopieren und Exportieren bleiben.
 */
function isSystem(p: ProcessOut): boolean { return isSystemProcess(p) }

/** Der Server hat wegen eines System-Prozesses abgewiesen – verständlich sagen. */
function reportSystemBlock(): void { showToast(SYSTEM_PROCESS_BLOCKED, false) }

const STATUS_TEXT: Record<string, string> = {
  draft: 'Entwurf', published: 'Veröffentlicht', archived: 'Archiviert',
}
const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  published: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  archived: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
}
function statusText(s: string) { return STATUS_TEXT[s] || s }
function statusBadge(s: string) { return STATUS_BADGE[s] || STATUS_BADGE.archived }

/** Backend liefert naive UTC-Zeitstempel – ohne 'Z' rechnet der Browser falsch. */
function formatDate(ts: string | null) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) =>
    (r.name || '').toLowerCase().includes(q) || r.key.toLowerCase().includes(q))
})

function sortVersions(list: ProcessOut[]): ProcessOut[] {
  return [...list].sort((a, b) => b.version - a.version)
}

/** Zeile pro Schlüssel: bevorzugt die veröffentlichte, sonst die höchste Version. */
function pickHead(list: ProcessOut[]): ProcessOut | null {
  if (!list.length) return null
  return list.find((v) => v.status === 'published') ?? sortVersions(list)[0]
}

function draftOf(key: string): ProcessOut | null {
  return versions.value[key]?.find((v) => v.status === 'draft') ?? null
}

// ── Laden ────────────────────────────────────────────────────────────────────

let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  try {
    let published: ProcessOut[] = []
    try {
      published = await listProcesses()
    } catch (e) {
      showToast(errorMessage(e, 'Prozesse konnten nicht geladen werden'), false)
    }
    if (my !== reqId) return

    const byKey = new Map<string, ProcessOut>()
    for (const p of published) byKey.set(p.key, p)

    // Entwürfe kennt nur dieser Browser – dafür einzeln die Versionen holen.
    const extra = loadKnownKeys().filter((k) => !byKey.has(k))
    const lists = await Promise.all(extra.map(async (k) => {
      try { return await listVersions(k) } catch { return [] as ProcessOut[] }
    }))
    if (my !== reqId) return

    for (const list of lists) {
      const head = pickHead(list)
      if (!head) continue
      byKey.set(head.key, head)
      // Gleich mitnehmen – spart beim Aufklappen einen Request.
      versions.value[head.key] = sortVersions(list)
    }

    rows.value = [...byKey.values()]
      .sort((a, b) => (a.name || a.key).localeCompare(b.name || b.key, 'de'))
  } finally {
    if (my === reqId) loading.value = false
  }
}

async function loadVersions(key: string, force = false) {
  if (!force && versions.value[key]) return
  busy.value = `v:${key}`
  try {
    versions.value[key] = sortVersions(await listVersions(key))
  } catch (e) {
    versions.value[key] = []
    if (errorCode(e) !== 'PROCESS_NOT_FOUND') {
      showToast(errorMessage(e, 'Versionen konnten nicht geladen werden'), false)
    }
  } finally {
    busy.value = null
  }
}

/** Vollständig neu laden; die aufgeklappte Zeile bekommt frische Versionen. */
async function reload() {
  const open = expanded.value
  versions.value = {}
  await load()
  if (open) await loadVersions(open, true)
}

function toggle(key: string) {
  if (expanded.value === key) { expanded.value = null; return }
  expanded.value = key
  loadVersions(key)
}

// ── Bearbeiten ───────────────────────────────────────────────────────────────

function goEditor(key: string, version: number) {
  router.push(`/prozesse/${encodeURIComponent(key)}/${version}`)
}

/** Ein fremder Entwurf wird übernommen – das darf nicht stillschweigend passieren. */
function warnForeignDraft(p: ProcessOut) {
  const me = auth.user?.id
  if (p.created_by && me && p.created_by !== me) {
    showToast(
      `Es wird ein offener Entwurf von ${p.created_by_name || p.created_by} weiterbearbeitet.`,
      false,
    )
  }
}

async function edit(row: ProcessOut) {
  if (row.status === 'draft') { goEditor(row.key, row.version); return }
  const cached = draftOf(row.key)
  if (cached) { warnForeignDraft(cached); goEditor(cached.key, cached.version); return }
  busy.value = `e:${row.key}`
  try {
    // Get-or-create: liefert einen bestehenden Entwurf zurück, sonst einen Klon.
    const out = await createDraft(row.key)
    rememberKey(out.key)
    warnForeignDraft(out)
    goEditor(out.key, out.version)
  } catch (e) {
    if (isSystemReadonlyError(e)) reportSystemBlock()
    else showToast(errorMessage(e, 'Entwurf konnte nicht geöffnet werden'), false)
  } finally {
    busy.value = null
  }
}

// ── Veröffentlichen / Löschen / Export ───────────────────────────────────────

async function publish(p: ProcessOut) {
  if (!confirm(
    `Version ${p.version} von „${p.name || p.key}“ veröffentlichen?\n\n`
    + 'Diese Version wird für neue Aufträge verbindlich.')) return
  busy.value = `p:${p.key}:${p.version}`
  try {
    await publishVersion(p.key, p.version)
    showToast(`„${p.name || p.key}“ v${p.version} veröffentlicht`)
    await reload()
  } catch (e) {
    if (isSystemReadonlyError(e)) reportSystemBlock()
    else showToast(errorMessage(e, 'Veröffentlichen fehlgeschlagen'), false)
  } finally {
    busy.value = null
  }
}

/**
 * Löschung des GANZEN Prozesses anfordern (alle Versionen + alle Aufträge).
 *
 * Löscht bewusst nichts direkt: der Server verschickt einen Bestätigungs-Link an
 * die hinterlegte Admin-Adresse. Erst dort wird gelöscht – ein Knopf allein wäre
 * für einen nicht umkehrbaren Eingriff dieser Größe zu wenig.
 */
async function requestDelete(r: ProcessOut) {
  if (!confirm(
    `Löschung von „${r.name || r.key}“ anfordern?

`
    + 'Es wird noch nichts gelöscht: an die hinterlegte Admin-Adresse geht ein '
    + 'Bestätigungs-Link. Gelöscht würden ALLE Versionen und ALLE Aufträge dieses '
    + 'Prozesses – das lässt sich dann nicht rückgängig machen.')) return
  busy.value = `rm:${r.key}`
  try {
    // Erster Versuch ohne Zustimmung zu den Aufträgen: gibt es welche, antwortet
    // der Server mit 409 und nennt die Anzahl – dann wird gezielt nachgefragt.
    let res
    try {
      res = await requestProcessDelete(r.key, false)
    } catch (e) {
      if (errorCode(e) !== 'PROCESS_DELETE_NEEDS_TICKETS') throw e
      if (!confirm(`${errorMessage(e, '')}

Mit den Aufträgen löschen?`)) return
      res = await requestProcessDelete(r.key, true)
    }
    showToast(`Bestätigungs-Mail an ${res.recipient} verschickt`
      + (res.tickets ? ` – betrifft ${res.tickets} Auftrag/Aufträge` : ''))
  } catch (e) {
    const code = errorCode(e)
    if (isSystemReadonlyError(e)) {
      reportSystemBlock()
    } else if (code === 'PROCESS_DELETE_NO_RECIPIENT') {
      showToast('Es ist keine Admin-Adresse hinterlegt (ADMIN_MAIL). Ohne sie kann '
        + 'kein Prozess gelöscht werden.', false)
    } else if (code === 'PROCESS_DELETE_MAIL_FAILED') {
      showToast('Die Bestätigungs-Mail konnte nicht versendet werden – es wurde '
        + 'nichts gelöscht.', false)
    } else {
      showToast(errorMessage(e, 'Löschung konnte nicht angefordert werden'), false)
    }
  } finally {
    busy.value = null
  }
}

/**
 * Prozess global (de)aktivieren. Nur bei veröffentlichten, nicht-System-Prozessen
 * sinnvoll: nur die sind anlegbar, und System-Prozesse sind ohnehin unantastbar.
 * Deaktiviert = niemand kann neue Aufträge anlegen; laufende bleiben unberührt.
 */
function canToggleActive(p: ProcessOut): boolean {
  return !isSystem(p) && p.status === 'published'
}

async function toggleActive(p: ProcessOut) {
  const willDisable = !p.disabled
  if (willDisable && !confirm(
    `„${p.name || p.key}“ deaktivieren?\n\n`
    + 'Es können danach keine neuen Aufträge dieses Prozesses mehr angelegt werden, '
    + 'bis er wieder freigegeben wird. Laufende Aufträge sind nicht betroffen.')) return
  busy.value = `a:${p.key}`
  try {
    await setProcessActive(p.key, willDisable)
    showToast(willDisable
      ? `„${p.name || p.key}“ deaktiviert – keine neuen Aufträge mehr möglich`
      : `„${p.name || p.key}“ wieder freigegeben`)
    await reload()
  } catch (e) {
    if (isSystemReadonlyError(e)) reportSystemBlock()
    else showToast(errorMessage(e, 'Statusänderung fehlgeschlagen'), false)
  } finally {
    busy.value = null
  }
}

async function remove(p: ProcessOut) {
  if (!confirm(
    `Entwurf v${p.version} von „${p.name || p.key}“ wirklich löschen?\n\n`
    + 'Dies wird im Audit-Log festgehalten.')) return
  busy.value = `d:${p.key}:${p.version}`
  try {
    await deleteVersion(p.key, p.version)
    showToast(`Entwurf v${p.version} gelöscht`)
    const rest = (versions.value[p.key] || []).filter((v) => v.version !== p.version)
    if (!rest.length) {
      // Letzte Version weg → der Schlüssel existiert nicht mehr.
      forgetKey(p.key)
      expanded.value = null
    }
    await reload()
  } catch (e) {
    const code = errorCode(e)
    if (isSystemReadonlyError(e)) {
      reportSystemBlock()
    } else if (code === 'PROCESS_VERSION_IN_USE') {
      showToast('Diese Version wird von bestehenden Aufträgen verwendet und kann nicht gelöscht werden.', false)
    } else if (code === 'PROCESS_INVALID_STATE') {
      showToast('Nur Entwürfe können gelöscht werden – veröffentlichte oder archivierte Versionen bleiben bestehen.', false)
    } else {
      showToast(errorMessage(e, 'Löschen fehlgeschlagen'), false)
    }
  } finally {
    busy.value = null
  }
}

async function download(key: string, version: number) {
  busy.value = `x:${key}:${version}`
  let url: string | null = null
  try {
    const defn = await exportVersion(key, version)
    const blob = new Blob([JSON.stringify(defn, null, 2)], { type: 'application/json' })
    url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `prozess_${key}_v${version}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch (e) {
    showToast(errorMessage(e, 'Export fehlgeschlagen'), false)
  } finally {
    // Erst nach dem Klick freigeben, sonst bricht der Download ab.
    if (url) { const u = url; setTimeout(() => URL.revokeObjectURL(u), 0) }
    busy.value = null
  }
}

// ── Modals ───────────────────────────────────────────────────────────────────

function openNew() {
  newMode.value = 'create'
  newSource.value = null
  newOpen.value = true
}

function openDuplicate(row: ProcessOut) {
  newMode.value = 'duplicate'
  newSource.value = row.key
  newOpen.value = true
}

async function onCreated(payload: { key: string; version: number }) {
  const wasDuplicate = newMode.value === 'duplicate'
  newOpen.value = false
  rememberKey(payload.key)
  if (wasDuplicate) {
    showToast(`Kopie „${payload.key}“ angelegt`)
    await reload()
  } else {
    goEditor(payload.key, payload.version)
  }
}

function onImported(payload: { key: string; version: number }) {
  importOpen.value = false
  rememberKey(payload.key)
  goEditor(payload.key, payload.version)
}

onMounted(load)
</script>

<template>
  <section>
    <h2 class="section-title mb-1">Prozesse</h2>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Prozess-Definitionen beschreiben Phasen, Felder und Automatisierungen eines Auftragstyps.
      Bearbeitet wird immer ein Entwurf; erst das Veröffentlichen macht eine Version für neue
      Aufträge verbindlich. Bereits laufende Aufträge behalten ihre Version.
      <br>
      <span class="text-xs">
        Hinweis: Noch nie veröffentlichte Entwürfe sind nur in dem Browser sichtbar, in dem sie
        angelegt wurden – der Server stellt dafür keine Liste bereit.
        Prozesse mit der Plakette „System“ gehören zum Produkt: sie werden automatisch aktuell
        gehalten und lassen sich kopieren, aber nicht ändern.
      </span>
    </div>

    <!-- Suche + Aktionen -->
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <input v-model="search" placeholder="Suche (Name, Schlüssel…)" class="afi flex-1 min-w-[14rem]" />
      <!-- BEWUSST kein Seed-Knopf mehr: Prozesse kommen manuell über
           „Importieren" (JSON aus dem Repo) oder werden hier neu gebaut. -->
      <button @click="importOpen = true" class="btn-secondary">Importieren</button>
      <button @click="openNew()" class="btn-primary">Neuer Prozess</button>
    </div>

    <div class="card-section !p-0 overflow-hidden">
      <div v-if="loading && rows.length === 0" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-gray-400 uppercase tracking-wider border-b dark:border-white/[0.06]">
              <th class="px-4 py-3">Name</th>
              <th class="px-4 py-3">Schlüssel</th>
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3">Version</th>
              <th class="px-4 py-3">Zuletzt geändert</th>
              <th class="px-4 py-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
            <template v-for="r in filtered" :key="r.key">
              <tr class="hover:bg-gray-50 dark:hover:bg-[#263040] transition align-top cursor-pointer"
                  @click="toggle(r.key)">
                <td class="px-4 py-3 text-gray-700 dark:text-gray-200 max-w-[18rem]">
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400 text-xs">{{ expanded === r.key ? '▾' : '▸' }}</span>
                    <span class="truncate font-medium">{{ r.name || 'Unbenannt' }}</span>
                  </div>
                </td>
                <td class="px-4 py-3 whitespace-nowrap font-mono text-xs text-gray-500 dark:text-gray-400">
                  {{ r.key }}
                </td>
                <td class="px-4 py-3 whitespace-nowrap">
                  <span class="text-[11px] font-medium px-2 py-0.5 rounded-full" :class="statusBadge(r.status)">
                    {{ statusText(r.status) }}
                  </span>
                  <span v-if="r.status !== 'draft' && draftOf(r.key)"
                        class="ml-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full
                               bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                    Entwurf offen
                  </span>
                  <!-- Plakette statt fehlender Knöpfe ohne Erklärung: der Tooltip
                       sagt, WARUM hier nichts zu ändern ist (ausführlich noch
                       einmal in der aufgeklappten Zeile). -->
                  <span v-if="isSystem(r)" :title="SYSTEM_PROCESS_HINT"
                        class="ml-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full cursor-help
                               bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                    System
                  </span>
                  <span v-if="r.disabled"
                        title="Deaktiviert – es lassen sich keine neuen Aufträge anlegen"
                        class="ml-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full
                               bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                    Deaktiviert
                  </span>
                </td>
                <td class="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-300">v{{ r.version }}</td>
                <td class="px-4 py-3 whitespace-nowrap text-gray-500 dark:text-gray-400">
                  {{ formatDate(r.updated_at) }}
                </td>
                <td class="px-4 py-3 whitespace-nowrap text-right">
                  <div class="flex items-center justify-end gap-2">
                    <button v-if="!isSystem(r)" @click.stop="edit(r)" :disabled="busy === `e:${r.key}`"
                            class="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                   text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5
                                   disabled:opacity-40 transition">
                      Bearbeiten
                    </button>
                    <!-- Global (de)aktivieren: sperrt/erlaubt das Anlegen neuer
                         Aufträge. Freigeben grün, Deaktivieren zurückhaltend. -->
                    <button v-if="canToggleActive(r)" @click.stop="toggleActive(r)"
                            :disabled="busy === `a:${r.key}`"
                            :class="['px-2.5 py-1 rounded-lg border transition disabled:opacity-40',
                                     r.disabled
                                       ? 'border-green-300 dark:border-green-500/40 text-green-700 dark:text-green-300 hover:bg-green-50 dark:hover:bg-green-900/20'
                                       : 'border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-amber-50 dark:hover:bg-amber-900/20 hover:text-amber-700']">
                      {{ r.disabled ? 'Freigeben' : 'Deaktivieren' }}
                    </button>
                    <button @click.stop="openDuplicate(r)"
                            class="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                   text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5
                                   transition">
                      Kopieren
                    </button>
                    <!-- Ganzen Prozess löschen: fordert nur an, die Bestätigung
                         läuft über die Admin-Adresse. Optisch zurückhaltend –
                         es ist der schärfste Eingriff in dieser Liste. -->
                    <button v-if="!isSystem(r)" @click.stop="requestDelete(r)"
                            :disabled="busy === `rm:${r.key}`"
                            title="Ganzen Prozess löschen (mit Mail-Bestätigung)"
                            class="px-2.5 py-1 rounded-lg text-gray-400 hover:text-red-600
                                   disabled:opacity-40 transition">
                      Löschen…
                    </button>
                    <button @click.stop="download(r.key, r.version)"
                            :disabled="busy === `x:${r.key}:${r.version}`"
                            class="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                   text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5
                                   disabled:opacity-40 transition">
                      Exportieren
                    </button>
                  </div>
                </td>
              </tr>

              <!-- Versionen -->
              <tr v-if="expanded === r.key" class="bg-gray-50 dark:bg-[#1A2130]">
                <td colspan="6" class="px-4 py-3">
                  <!-- Warum an diesem Prozess keine Aktionen stehen. Gehört sichtbar
                       hierher, nicht nur in einen Tooltip. -->
                  <p v-if="isSystem(r)"
                     class="rounded-xl border border-purple-200 dark:border-purple-500/30
                            bg-purple-50 dark:bg-purple-900/20 px-4 py-3 mb-2
                            text-xs text-purple-900 dark:text-purple-200">
                    <span class="font-medium">System-Prozess.</span>
                    {{ SYSTEM_PROCESS_HINT }}
                  </p>
                  <div v-if="busy === `v:${r.key}` && !versions[r.key]" class="flex items-center justify-center py-6">
                    <div class="w-6 h-6 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
                  </div>
                  <p v-else-if="!versions[r.key] || versions[r.key].length === 0"
                     class="text-sm text-gray-400 italic px-1">Keine Versionen gefunden.</p>
                  <div v-else class="space-y-1.5">
                    <div v-for="v in versions[r.key]" :key="v.version"
                         class="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl
                                border border-gray-200 dark:border-white/10 bg-white dark:bg-[#212B3A]
                                px-3 py-2">
                      <span class="font-medium text-gray-700 dark:text-gray-200 w-12">v{{ v.version }}</span>
                      <span class="text-[11px] font-medium px-2 py-0.5 rounded-full" :class="statusBadge(v.status)">
                        {{ statusText(v.status) }}
                      </span>
                      <span class="text-xs text-gray-500 dark:text-gray-400">
                        {{ formatDate(v.updated_at) }}
                      </span>
                      <span v-if="v.created_by_name" class="text-xs text-gray-400">
                        von {{ v.created_by_name }}
                      </span>
                      <span v-if="v.base_version" class="text-xs text-gray-400">
                        (aus v{{ v.base_version }})
                      </span>

                      <div class="flex items-center gap-2 ml-auto">
                        <button v-if="v.status === 'draft' && !isSystem(r)"
                                @click="goEditor(v.key, v.version)"
                                class="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                       text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5
                                       transition">
                          Bearbeiten
                        </button>
                        <button v-if="v.status === 'draft' && !isSystem(r)" @click="publish(v)"
                                :disabled="busy === `p:${v.key}:${v.version}`"
                                class="px-2.5 py-1 rounded-lg bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                                       disabled:opacity-40 transition">
                          Veröffentlichen
                        </button>
                        <button @click="download(v.key, v.version)"
                                :disabled="busy === `x:${v.key}:${v.version}`"
                                class="px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                       text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5
                                       disabled:opacity-40 transition">
                          Exportieren
                        </button>
                        <button v-if="v.status === 'draft' && !isSystem(r)" @click="remove(v)"
                                :disabled="busy === `d:${v.key}:${v.version}`"
                                class="px-2.5 py-1 rounded-lg text-red-500 hover:text-red-600
                                       hover:bg-red-50 dark:hover:bg-red-900/20
                                       disabled:opacity-40 transition">
                          Löschen
                        </button>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>

            <tr v-if="filtered.length === 0 && !loading">
              <td colspan="6" class="px-4 py-12 text-center text-sm">
                <p class="text-gray-400 italic">Keine Prozesse gefunden</p>
                <!-- Leerer Katalog ist meist eine frische Installation: die
                     mitgelieferten Definitionen sind noch nicht eingespielt.
                     Der nächste Schritt gehört hierher, nicht in eine Server-Shell. -->
                <p v-if="!search.trim() && rows.length === 0" class="text-gray-400 mt-2 max-w-lg mx-auto">
                  Mit „Mitgelieferte Prozesse einspielen“ lassen sich die ausgelieferten
                  Definitionen anlegen – erst als Trockenlauf, dann nach Bestätigung.
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="flex items-center justify-between text-sm text-gray-400 mt-3">
      <span>{{ filtered.length }} Prozesse</span>
    </div>

    <NewProcessModal :open="newOpen" :mode="newMode" :source-key="newSource"
                     @close="newOpen = false" @created="onCreated" />
    <ImportProcessModal :open="importOpen"
                        @close="importOpen = false" @imported="onImported" />
  </section>
</template>

