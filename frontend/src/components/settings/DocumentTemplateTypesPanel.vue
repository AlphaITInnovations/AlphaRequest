<script setup lang="ts">
/**
 * Dokument-Vorlagen-Typen verwalten (Arbeitsvertrag, Kündigung …). Der Typ ist die
 * gemeinsame Klammer: Firmen laden ihre Vorlagen je Typ hoch, der Prozess bindet die
 * {{Marker}} EINMAL je Typ. Darum müssen alle Firmen-Vorlagen eines Typs denselben
 * Platzhalter-Satz haben – er wird beim ersten Upload erfasst und hier angezeigt.
 */
import { computed, onMounted, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { listTemplateLabels, saveTemplateLabels, type TemplateLabel } from '@/api/templateLabels'

const { showToast } = useToast()
const names = ref<string[]>([])
/** Server-Name je Zeile (Index-gleich zu `names`), um Metadaten auch nach einem
 *  In-Place-Umbenennen korrekt nachzuschlagen; '' = neue, noch ungespeicherte Zeile. */
const orig = ref<string[]>([])
/** Server-Metadaten je (Server-)Typname (Marker + nutzende Firmen) – nur Anzeige. */
const meta = ref<Record<string, { placeholders: string[] | null; companies: string[] }>>({})
const snapshot = ref('')
const loading = ref(true)
const newName = ref('')

function apply(labels: TemplateLabel[]) {
  names.value = labels.map(l => l.name)
  orig.value = labels.map(l => l.name)
  meta.value = Object.fromEntries(labels.map(l => [l.name, {
    placeholders: l.placeholders, companies: l.companies,
  }]))
  snapshot.value = JSON.stringify(names.value)
}
/** Metadaten einer Zeile über ihren SERVER-Namen (stabil bei Umbenennen). */
function metaFor(i: number) {
  const o = orig.value[i]
  return o ? meta.value[o] : undefined
}

async function load() {
  loading.value = true
  try {
    apply(await listTemplateLabels())
  } finally {
    loading.value = false
  }
}

function add() {
  const n = newName.value.trim()
  if (!n) return
  if (names.value.some(x => x.toLowerCase() === n.toLowerCase())) {
    showToast('Diesen Typ gibt es schon', false); return
  }
  names.value.push(n)
  orig.value.push('')               // neue Zeile: kein Server-Name
  newName.value = ''
}
function removeAt(i: number) {
  const n = names.value[i]
  const firmen = metaFor(i)?.companies ?? []
  if (firmen.length && !confirm(
    `„${n}“ wird von ${firmen.length} Firma(en) genutzt. Der Typ lässt sich erst `
    + `entfernen, wenn dort die Vorlagen gelöscht sind. Trotzdem versuchen?`)) return
  names.value.splice(i, 1)
  orig.value.splice(i, 1)
}

async function save() {
  for (const n of names.value) {
    if (!n.trim()) { showToast('Leere Typ-Namen sind nicht erlaubt', false); return }
  }
  setSaving(true)
  try {
    apply(await saveTemplateLabels(names.value))
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.response?.data?.error?.message
      || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => JSON.stringify(names.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save, reset: load })

const markerLabel = (i: number) => {
  const m = metaFor(i)
  const ph = m?.placeholders
  if (ph == null) return 'noch keine Vorlage'
  return ph.length === 1 ? '1 Platzhalter' : `${ph.length} Platzhalter`
}
const markerHint = '{{Marker}}'   // als Konstante, sonst kollidiert {{…}} mit der Template-Syntax

onMounted(load)
</script>

<template>
  <section>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Dokument-Vorlagen-Typen</h2>
    </div>

    <div class="rounded-xl border border-gray-200/80 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20
                px-4 py-3 text-sm text-amber-800 dark:text-amber-200 mb-4">
      Typen sind die gemeinsame Klammer für firmenabhängige Dokumente. Firmen laden ihre Vorlagen je Typ
      hoch (Einstellungen → Firmen), der Prozess bindet die {{ markerHint }} einmal je Typ. Deshalb müssen
      <b>alle Firmen-Vorlagen eines Typs dieselben Platzhalter</b> haben – der erste Upload legt den Satz fest,
      weitere werden geprüft.
    </div>

    <p v-if="loading" class="text-sm text-gray-400 italic">Lädt …</p>

    <template v-else>
      <ul v-if="names.length" class="space-y-2 mb-4">
        <li v-for="(_n, i) in names" :key="i"
            class="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-white/10
                   bg-white dark:bg-white/[0.03] px-4 py-3">
          <input v-model="names[i]" class="set-input flex-1 font-medium" maxlength="150"
                 placeholder="Typ-Name (z. B. Arbeitsvertrag)" />
          <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-500 dark:text-gray-300 whitespace-nowrap">
            {{ markerLabel(i) }}
          </span>
          <span v-if="metaFor(i)?.companies?.length"
                class="text-xs text-gray-400 truncate max-w-[14rem]" :title="metaFor(i)!.companies.join(', ')">
            {{ metaFor(i)!.companies.length }} Firma(en)
          </span>
          <button type="button" @click="removeAt(i)"
                  class="text-sm text-red-500 hover:text-red-600 hover:underline whitespace-nowrap">Entfernen</button>
        </li>
      </ul>
      <p v-else class="text-sm text-gray-400 italic mb-4">Noch keine Vorlagen-Typen angelegt.</p>

      <div class="flex items-center gap-2">
        <input v-model="newName" @keyup.enter="add" class="set-input flex-1" maxlength="150"
               placeholder="Neuer Typ (z. B. Kündigung)" />
        <button type="button" @click="add" class="btn-secondary text-sm whitespace-nowrap">+ Typ hinzufügen</button>
      </div>
    </template>
  </section>
</template>
