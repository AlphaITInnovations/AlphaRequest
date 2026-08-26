<script setup lang="ts">
/**
 * Verwaltung der Directus-Quellen für Auswahl-Felder (Kostenstelle,
 * Niederlassung …). Directus wird LIVE abgefragt: Collection und Felder werden
 * aus dem Schema angeboten, eine Vorschau testet die Konfiguration vor dem
 * Speichern. Gespeichert wird per bulk-replace (wie Firmen), mit der Save-Bar
 * der Einstellungen (useSaver).
 */
import { ref, computed, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { useDetailNav } from '@/composables/useDetailNav'
import SettingsList from '@/components/settings/SettingsList.vue'
import {
  type DirectusSource, type DirectusStatus, type DirectusCollection,
  type DirectusField, type DirectusOption,
  getStatus, listSources, saveSources, listCollections, listFields, previewSource,
} from '@/api/directus'

const { showToast } = useToast()

const sources = ref<DirectusSource[]>([])
const snapshot = ref('')
const loading = ref(true)
const status = ref<DirectusStatus>({ configured: false, ok: false, error: null })
const collections = ref<DirectusCollection[]>([])
const fieldsByCollection = ref<Record<string, DirectusField[]>>({})

const { selected, open, back } = useDetailNav(() => sources.value.length)

// Vorschau (pro geöffneter Quelle)
const previewLoading = ref(false)
const previewOptions = ref<DirectusOption[]>([])
const previewError = ref<string | null>(null)
const filterErr = ref<string | null>(null)

function serialize(list: DirectusSource[]): string { return JSON.stringify(list) }

// Literale {{ }} im Template brechen den Vue-Compiler – Mustache-Text über
// Script-Helfer bauen (PH_LABEL_EXAMPLE als Platzhalter, varLabel für die Chips).
const PH_LABEL_EXAMPLE = '{{nummer}} – {{firma.name}}'
function varLabel(p: string): string { return '{{' + p + '}}' }

function blank(): DirectusSource {
  return { key: '', label: '', collection: '', valueField: '', labelTemplate: '',
           fields: [], filter: null, sort: [], limit: 200 }
}

async function loadAll() {
  loading.value = true
  try {
    status.value = await getStatus().catch(() => ({ configured: false, ok: false, error: null }))
    sources.value = await listSources()
    snapshot.value = serialize(sources.value)
    // Collections nur laden, wenn Directus antwortet – sonst bleibt die manuelle Eingabe.
    if (status.value.ok) {
      collections.value = await listCollections().catch(() => [])
    }
  } finally {
    loading.value = false
  }
}

async function ensureFields(collection: string) {
  if (!collection || fieldsByCollection.value[collection] || !status.value.ok) return
  try {
    fieldsByCollection.value = { ...fieldsByCollection.value, [collection]: await listFields(collection) }
  } catch { /* Introspektion optional – manuelle Pfade bleiben möglich */ }
}

function currentFields(s: DirectusSource): DirectusField[] {
  return fieldsByCollection.value[s.collection] ?? []
}

function addSource() {
  sources.value.push(blank())
  open(sources.value.length - 1)
  resetPreview()
}
function removeSource(idx: number) {
  const s = sources.value[idx]
  if ((s.key || s.label) && !confirm(`Quelle „${s.label || s.key}“ wirklich entfernen?`)) return
  sources.value.splice(idx, 1)
  back()
}

function onOpen(idx: number) {
  open(idx)
  resetPreview()
  ensureFields(sources.value[idx]?.collection)
}
function onCollectionChange(s: DirectusSource) {
  // Feldbezüge zurücksetzen: sie gehören zur alten Collection.
  s.valueField = ''
  s.fields = []
  resetPreview()
  ensureFields(s.collection)
}

// ── Feld-/Label-Helfer ────────────────────────────────────────────────────────

function toggleField(s: DirectusSource, path: string) {
  const i = s.fields.indexOf(path)
  if (i >= 0) s.fields.splice(i, 1)
  else s.fields.push(path)
}
const pathToAdd = ref('')
function addPath(s: DirectusSource) {
  const p = pathToAdd.value.trim()
  if (p && !s.fields.includes(p)) s.fields.push(p)
  pathToAdd.value = ''
}
function insertVar(s: DirectusSource, path: string) {
  s.labelTemplate = (s.labelTemplate ? s.labelTemplate + ' ' : '') + `{{${path}}}`
}

/** Alle vorschlagbaren Pfade fürs Label: Top-Level-Felder + bereits gewählte Pfade. */
function suggestPaths(s: DirectusSource): string[] {
  const top = currentFields(s).map((f) => f.field)
  return [...new Set([...top, ...s.fields])]
}

function filterDisplay(s: DirectusSource): string {
  return s.filter ? JSON.stringify(s.filter, null, 2) : ''
}
function setFilter(s: DirectusSource, raw: string) {
  const t = raw.trim()
  if (!t) { s.filter = null; filterErr.value = null; return }
  try { s.filter = JSON.parse(t); filterErr.value = null }
  catch (e: any) { filterErr.value = 'Kein gültiges JSON: ' + (e?.message ?? '') }
}
function parseCsv(raw: string): string[] {
  return raw.split(',').map((x) => x.trim()).filter(Boolean)
}

function resetPreview() {
  previewOptions.value = []
  previewError.value = null
  previewLoading.value = false
  filterErr.value = null
}

async function runPreview(s: DirectusSource) {
  previewError.value = null
  previewLoading.value = true
  previewOptions.value = []
  try {
    const res = await previewSource(s)
    previewOptions.value = res.options
    if (!res.options.length) previewError.value = 'Keine Datensätze gefunden (Filter/Collection prüfen).'
  } catch (e: any) {
    previewError.value = e?.response?.data?.error?.message || 'Vorschau fehlgeschlagen.'
  } finally {
    previewLoading.value = false
  }
}

// ── Speichern ──────────────────────────────────────────────────────────────────

const slugRe = /^[a-z0-9][a-z0-9_-]*$/

async function save() {
  const keys = new Set<string>()
  for (const s of sources.value) {
    const k = (s.key || '').trim().toLowerCase()
    if (!slugRe.test(k)) { showToast(`Ungültiger Schlüssel „${s.key}“ (nur a–z, 0–9, _ und -)`, false); return }
    if (keys.has(k)) { showToast(`Doppelter Schlüssel „${k}“`, false); return }
    keys.add(k)
    if (!s.collection.trim()) { showToast(`Quelle „${k}“: Collection fehlt`, false); return }
    if (!s.valueField.trim()) { showToast(`Quelle „${k}“: Wert-Feld fehlt`, false); return }
    if (!s.labelTemplate.trim()) { showToast(`Quelle „${k}“: Label-Vorlage fehlt`, false); return }
  }
  if (filterErr.value) { showToast('Bitte den Filter korrigieren (kein gültiges JSON).', false); return }
  setSaving(true)
  try {
    sources.value = await saveSources(sources.value.map((s) => ({ ...s, key: s.key.trim().toLowerCase() })))
    snapshot.value = serialize(sources.value)
    back()
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => serialize(sources.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save, reset: () => loadAll() })

onMounted(loadAll)
</script>

<template>
  <section>
    <!-- Verbindungs-Banner -->
    <div v-if="!status.configured"
         class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20
                px-4 py-3 text-sm text-amber-800 dark:text-amber-200 mb-3">
      Directus ist nicht konfiguriert. Setze <code>DIRECTUS_URL</code> und
      <code>DIRECTUS_TOKEN</code> in der <code>.env</code>, um Collections & Felder live auszuwählen.
      Quellen lassen sich trotzdem manuell anlegen.
    </div>
    <div v-else-if="!status.ok"
         class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                px-4 py-3 text-sm text-red-800 dark:text-red-200 mb-3">
      Directus nicht erreichbar: {{ status.error }}
    </div>
    <div v-else
         class="rounded-xl border border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-900/20
                px-4 py-3 text-sm text-green-800 dark:text-green-200 mb-3">
      Mit Directus verbunden.
    </div>

    <!-- Liste -->
    <SettingsList v-if="selected === null" title="Directus-Quellen" :items="sources" :loading="loading"
                  add-label="+ Quelle hinzufügen" search-placeholder="Quelle suchen…"
                  empty-text="Noch keine Quellen. Lege eine an (z. B. Kostenstelle, Niederlassung)."
                  :filter-text="(s) => s.label + ' ' + s.key + ' ' + s.collection"
                  @add="addSource" @select="onOpen">
      <template #row="{ item }">
        <span class="flex-1 min-w-0 truncate font-medium text-gray-900 dark:text-white">
          {{ item.label || item.key || 'Unbenannt' }}
        </span>
        <span class="text-xs text-gray-400 truncate hidden sm:inline">{{ item.key }}</span>
        <span v-if="item.collection" class="text-xs px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] whitespace-nowrap">
          {{ item.collection }}
        </span>
      </template>
    </SettingsList>

    <!-- Editor -->
    <template v-else-if="sources[selected]">
      <div class="flex items-center justify-between mb-4">
        <button @click="back()" class="btn-secondary">← Zurück</button>
        <button @click="removeSource(selected)"
                class="text-sm text-red-500 hover:text-red-600 hover:underline">Quelle entfernen</button>
      </div>

      <div class="card-section space-y-4">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Anzeigename</label>
            <input v-model="sources[selected].label" class="set-input w-full" placeholder="z. B. Kostenstelle" />
          </div>
          <div>
            <label class="lbl">Schlüssel <span class="text-gray-400 font-normal">(stabil, im Prozess referenziert)</span></label>
            <input v-model="sources[selected].key" class="set-input w-full" placeholder="kostenstelle" />
          </div>
        </div>

        <div>
          <label class="lbl">Collection</label>
          <select v-if="collections.length" v-model="sources[selected].collection"
                  @change="onCollectionChange(sources[selected])" class="set-input w-full">
            <option value="">Bitte wählen</option>
            <option v-for="c in collections" :key="c.collection" :value="c.collection">
              {{ c.collection }}<template v-if="c.note"> — {{ c.note }}</template>
            </option>
          </select>
          <input v-else v-model="sources[selected].collection" @change="onCollectionChange(sources[selected])"
                 class="set-input w-full" placeholder="Collection-Name (manuell, Directus nicht verbunden)" />
        </div>

        <!-- Felder, die geladen werden -->
        <div v-if="sources[selected].collection">
          <label class="lbl">Zu ladende Felder</label>
          <div v-if="currentFields(sources[selected]).length" class="flex flex-wrap gap-2 mb-2">
            <label v-for="f in currentFields(sources[selected])" :key="f.field"
                   class="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-lg border cursor-pointer select-none"
                   :class="sources[selected].fields.includes(f.field)
                     ? 'border-[#3EAAB8] bg-[#3EAAB8]/10 text-[#3EAAB8]'
                     : 'border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300'">
              <input type="checkbox" class="hidden"
                     :checked="sources[selected].fields.includes(f.field)"
                     @change="toggleField(sources[selected], f.field)" />
              {{ f.field }}
              <span v-if="f.relatedCollection" class="text-[10px] text-gray-400">→ {{ f.relatedCollection }}</span>
            </label>
          </div>
          <div class="flex flex-wrap gap-1.5 mb-2">
            <span v-for="p in sources[selected].fields" :key="p"
                  class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200">
              {{ p }}
              <button @click="toggleField(sources[selected], p)" class="text-gray-400 hover:text-red-500">×</button>
            </span>
          </div>
          <div class="flex gap-2">
            <input v-model="pathToAdd" @keyup.enter="addPath(sources[selected])" class="set-input flex-1"
                   placeholder="Relationalen Pfad ergänzen, z. B. firma.name" />
            <button @click="addPath(sources[selected])" class="btn-secondary text-sm">Hinzufügen</button>
          </div>
          <p class="text-xs text-gray-400 mt-1">
            Für Relationen (→ Ziel-Collection) den Unterfeld-Pfad mit Punkt angeben, z. B. <code>firma.name</code>.
          </p>
        </div>

        <div v-if="sources[selected].collection" class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Wert-Feld <span class="text-gray-400 font-normal">(wird gespeichert)</span></label>
            <select v-if="currentFields(sources[selected]).length" v-model="sources[selected].valueField" class="set-input w-full">
              <option value="">Bitte wählen</option>
              <option v-for="f in currentFields(sources[selected])" :key="f.field" :value="f.field">
                {{ f.field }}<template v-if="f.primaryKey"> (Schlüssel)</template>
              </option>
            </select>
            <input v-else v-model="sources[selected].valueField" class="set-input w-full" placeholder="z. B. nummer" />
          </div>
          <div>
            <label class="lbl">Limit</label>
            <input v-model.number="sources[selected].limit" type="number" min="1" max="1000" class="set-input w-full" />
          </div>
        </div>

        <!-- Label-Vorlage -->
        <div v-if="sources[selected].collection">
          <label class="lbl">Label-Vorlage <span class="text-gray-400 font-normal">(so erscheint die Option im Dropdown)</span></label>
          <input v-model="sources[selected].labelTemplate" class="set-input w-full"
                 :placeholder="PH_LABEL_EXAMPLE" />
          <div v-if="suggestPaths(sources[selected]).length" class="flex flex-wrap gap-1.5 mt-2">
            <button v-for="p in suggestPaths(sources[selected])" :key="p"
                    @click="insertVar(sources[selected], p)"
                    class="text-xs px-2 py-0.5 rounded-full border border-gray-200 dark:border-white/10
                           text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8] hover:text-[#3EAAB8]">
              + {{ varLabel(p) }}
            </button>
          </div>
        </div>

        <!-- Erweitert -->
        <details class="rounded-xl border border-gray-200 dark:border-white/10 px-3 py-2">
          <summary class="text-sm font-medium text-gray-700 dark:text-gray-300 cursor-pointer">Erweitert (Filter, Sortierung)</summary>
          <div class="pt-3 space-y-3">
            <div>
              <label class="lbl">Sortierung <span class="text-gray-400 font-normal">(Felder, kommagetrennt; „-feld" absteigend)</span></label>
              <input :value="sources[selected].sort.join(', ')"
                     @input="sources[selected].sort = parseCsv(($event.target as HTMLInputElement).value)"
                     class="set-input w-full" placeholder="nummer" />
            </div>
            <div>
              <label class="lbl">Filter <span class="text-gray-400 font-normal">(Directus-Filter als JSON)</span></label>
              <textarea :value="filterDisplay(sources[selected])"
                        @input="setFilter(sources[selected], ($event.target as HTMLTextAreaElement).value)"
                        rows="4" class="set-input w-full font-mono text-xs"
                        placeholder='{ "aktiv": { "_eq": true } }' />
              <p v-if="filterErr" class="text-xs text-red-500 mt-1">{{ filterErr }}</p>
            </div>
          </div>
        </details>

        <!-- Vorschau -->
        <div class="border-t border-gray-100 dark:border-white/10 pt-3">
          <div class="flex items-center gap-3">
            <button @click="runPreview(sources[selected])" :disabled="previewLoading" class="btn-secondary text-sm">
              {{ previewLoading ? 'Lädt…' : 'Vorschau' }}
            </button>
            <span class="text-xs text-gray-400">Testet die Abfrage live gegen Directus.</span>
          </div>
          <p v-if="previewError" class="text-sm text-amber-600 dark:text-amber-400 mt-2">{{ previewError }}</p>
          <ul v-if="previewOptions.length" class="mt-2 space-y-1">
            <li v-for="(o, i) in previewOptions.slice(0, 10)" :key="i"
                class="flex items-center justify-between gap-3 text-sm px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-white/5">
              <span class="truncate text-gray-800 dark:text-gray-100">{{ o.label }}</span>
              <span class="text-xs text-gray-400 whitespace-nowrap">{{ o.value }}</span>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </section>
</template>
