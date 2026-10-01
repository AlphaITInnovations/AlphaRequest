<script setup lang="ts">
/**
 * Editor für EIN Dokument einer Dokument-Phase: Titel, Dateiname, hochgeladene
 * Vorlage (.docx ODER PDF) und die {{marker}}→Feld-Zuordnung.
 *
 * Wie im Einzel-Dokument-Fall liegt die Vorlage-DATEI NICHT in der Definition,
 * sondern als Blob je (Prozess, Phase, Dokument) am Server – daher direkte
 * API-Aufrufe. Die {{marker}}-ZUORDNUNG (bindings) ist Definition und wird über
 * `@update` in den Entwurf gehoben.
 */
import { computed, onMounted, ref, watch } from 'vue'
import type { Condition, DocumentBinding, DocumentSpec, FieldDef } from '@/types/process'
import { TODAY_BINDING } from '@/types/process'
import {
  deleteDocumentTemplate, getDocumentTemplate, uploadDocumentTemplate,
  type DocumentTemplateInfo,
} from '@/api/processes'
import { listTemplateLabels, type TemplateLabel } from '@/api/templateLabels'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'
import ConditionEditor from './ConditionEditor.vue'

const props = withDefaults(defineProps<{
  processKey: string | null
  phaseKey: string
  /** Phasen-Index – Teil des Watch-Schlüssels, damit ein Phasenwechsel neu lädt. */
  index: number
  doc: DocumentSpec
  catalog?: FieldDef[]
  readonly?: boolean
  canRemove?: boolean
}>(), { catalog: () => [], readonly: false, canRemove: false })

const emit = defineEmits<{ update: [part: Partial<DocumentSpec>]; remove: [] }>()

const { showToast } = useToast()
const template = ref<DocumentTemplateInfo | null>(null)
const tplLoading = ref(false)
const tplBusy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const formatLabel = computed(() => (template.value?.format === 'pdf' ? 'PDF' : 'Word (.docx)'))

// ── Firmen-Vorlage (nach Vorlagen-TYP) vs. feste Hochlade-Vorlage ─────────────
const companyMode = ref<boolean>(!!(props.doc.companyTemplate || props.doc.companyField))
/** Registrierte Vorlagen-Typen (Dropdown + kanonischer Marker-Satz je Typ). */
const labels = ref<TemplateLabel[]>([])

/** Felder, die eine Firma halten (widget=company) – Quelle fürs companyField. */
const companyFields = computed(() =>
  (props.catalog ?? []).filter((f) => f.widget === 'company' && f.key)
    .map((f) => ({ key: f.key, label: f.label || f.key })))

/** Genau EINE der beiden Angaben gesetzt → ungültig (beide zusammen nötig). */
const companyHalfSet = computed(() =>
  companyMode.value && (!!props.doc.companyTemplate !== !!props.doc.companyField))

/** Kanonischer Platzhalter-Satz des gewählten Typs (bei allen Firmen gleich – hart
 *  geprüft beim Upload). null = Typ hat noch keine Vorlage. */
const typeLabel = computed(() =>
  labels.value.find((l) => l.name === props.doc.companyTemplate) ?? null)
const typePlaceholders = computed<string[]>(() => typeLabel.value?.placeholders ?? [])
/** Gespeicherter Typ, den es (nach Löschen/Umbenennen) nicht mehr gibt. */
const typeUnknown = computed(() =>
  !!props.doc.companyTemplate && labels.value.length > 0 && !typeLabel.value)

/** Platzhalter: im Hochlade-Modus aus der Datei, im Firmen-Modus aus dem Typ PLUS
 *  den bereits zugeordneten Markern (eine Zuordnung je Typ für alle Firmen). */
const placeholders = computed<string[]>(() => {
  if (!companyMode.value) return template.value?.placeholders ?? []
  return [...new Set([...typePlaceholders.value, ...Object.keys(props.doc.bindings ?? {})])]
})

async function loadLabels() {
  try { labels.value = await listTemplateLabels() } catch { labels.value = [] }
}

function setCompanyMode(on: boolean) {
  if (on === companyMode.value) return
  companyMode.value = on
  if (on) {
    emit('update', { companyTemplate: props.doc.companyTemplate ?? '',
                     companyField: props.doc.companyField ?? (companyFields.value[0]?.key ?? '') })
  } else {
    emit('update', { companyTemplate: null, companyField: null })
  }
}

// Die Vorlage liegt je (Prozess, PHASE, DOKUMENT) → alle drei Schlüssel nötig.
const templateReady = computed(() => !!props.processKey && !!props.phaseKey && !!props.doc.key)

async function loadTemplate() {
  if (!templateReady.value) { template.value = null; return }
  tplLoading.value = true
  try {
    template.value = await getDocumentTemplate(props.processKey!, props.phaseKey, props.doc.key)
  } catch {
    template.value = null       // Kein Vorlage-Endpunkt / kein Zugriff: still degradieren.
  } finally {
    tplLoading.value = false
  }
}
onMounted(() => { loadTemplate(); loadLabels() })
watch(() => `${props.processKey} ${props.index} ${props.phaseKey} ${props.doc.key}`, () => {
  loadTemplate()
  // Der Editor wird bei einem Phasenwechsel wiederverwendet (zwei Dokument-Phasen
  // teilen oft den doc.key „dokument"). Ohne Resync bliebe der Modus des vorigen
  // Dokuments „kleben" und ein Tippen würde das falsche Dokument umschalten.
  companyMode.value = !!(props.doc.companyTemplate || props.doc.companyField)
})

function pickFile() { fileInput.value?.click() }

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''              // dieselbe Datei erneut wählbar machen
  if (!file || !templateReady.value) return
  const nm = file.name.toLowerCase()
  if (!(nm.endsWith('.docx') || nm.endsWith('.pdf'))) {
    showToast('Bitte eine .docx- oder PDF-Datei wählen.', false); return
  }
  tplBusy.value = true
  try {
    template.value = await uploadDocumentTemplate(props.processKey!, props.phaseKey, file, props.doc.key)
    pruneBindings()             // Zuordnungen auf die neuen Marker eindampfen
    showToast('Vorlage hochgeladen.')
  } catch (err) {
    showToast(errorMessage(err, 'Upload fehlgeschlagen.'), false)
  } finally {
    tplBusy.value = false
  }
}

async function removeTemplate() {
  if (!templateReady.value) return
  tplBusy.value = true
  try {
    await deleteDocumentTemplate(props.processKey!, props.phaseKey, props.doc.key)
    template.value = { exists: false }
  } catch (err) {
    showToast(errorMessage(err, 'Löschen fehlgeschlagen.'), false)
  } finally {
    tplBusy.value = false
  }
}

function bindingFor(marker: string): string {
  return props.doc.bindings?.[marker]?.field ?? ''
}
function bindingOffset(marker: string): number | '' {
  const o = props.doc.bindings?.[marker]?.offset
  return (o === null || o === undefined) ? '' : o
}
function isFieldBinding(marker: string): boolean {
  const f = bindingFor(marker)
  return !!f && f !== TODAY_BINDING
}
function setBinding(marker: string, field: string) {
  const next: Record<string, DocumentBinding> = { ...(props.doc.bindings ?? {}) }
  if (!field) delete next[marker]
  else if (field === TODAY_BINDING) next[marker] = { field }
  else next[marker] = { field, offset: next[marker]?.offset ?? null }
  emit('update', { bindings: next })
}
function setOffset(marker: string, raw: string) {
  const cur = props.doc.bindings?.[marker]
  if (!cur || cur.field === TODAY_BINDING) return
  const n = raw.trim() === '' ? null : Number.parseInt(raw, 10)
  const next: Record<string, DocumentBinding> = { ...(props.doc.bindings ?? {}) }
  next[marker] = { field: cur.field, offset: (n === null || Number.isNaN(n)) ? null : n }
  emit('update', { bindings: next })
}
/** Zuordnungen zu nicht mehr vorhandenen Markern verwerfen (nach Neu-Upload). */
function pruneBindings() {
  const cur = props.doc.bindings ?? {}
  const known = new Set(placeholders.value)
  const next: Record<string, DocumentBinding> = {}
  for (const [k, v] of Object.entries(cur)) if (known.has(k)) next[k] = v
  if (Object.keys(next).length !== Object.keys(cur).length) emit('update', { bindings: next })
}

const bindableFields = computed(() =>
  (props.catalog ?? [])
    .filter((f) => f.key
      && f.widget !== 'attachment' && f.widget !== 'collection'
      && f.widget !== 'user' && f.widget !== 'group'
      && f.optionsSource !== 'users' && f.optionsSource !== 'groups')
    .map((f) => ({ key: f.key, label: f.label || f.key })))

// ── Bedingte Passagen (sections): {{#if:NAME}} … {{/if}} in der .docx ──────────
const sectionEntries = computed<Array<[string, Condition]>>(() =>
  Object.entries(props.doc.sections ?? {}))
function freshSectionName(): string {
  const used = new Set(Object.keys(props.doc.sections ?? {}))
  if (!used.has('passus')) return 'passus'
  let i = 2
  while (used.has(`passus_${i}`)) i += 1
  return `passus_${i}`
}
function addSection() {
  emit('update', { sections: { ...(props.doc.sections ?? {}), [freshSectionName()]: { truthy: '' } } })
}
function removeSection(name: string) {
  const next = { ...(props.doc.sections ?? {}) }
  delete next[name]
  emit('update', { sections: next })
}
function renameSection(oldName: string, raw: string) {
  const nn = raw.trim()
  const src = props.doc.sections ?? {}
  if (!nn || nn === oldName) return
  if (src[nn] !== undefined) { showToast('Dieser Passus-Name ist schon vergeben.', false); return }
  const next: Record<string, Condition> = {}       // Reihenfolge erhalten
  for (const [k, v] of Object.entries(src)) next[k === oldName ? nn : k] = v
  emit('update', { sections: next })
}
function setSectionCond(name: string, cond: Condition | null) {
  emit('update', { sections: { ...(props.doc.sections ?? {}), [name]: cond ?? {} } })
}

const PH_HINT = '{{…}}'
function markerLabel(m: string): string { return '{{' + m + '}}' }
const ifHint = '{{#if:passus}} … {{/if}}'
const mappedCount = computed(() => placeholders.value.filter((m) => !!bindingFor(m)).length)
const uploadedAtLabel = computed(() => {
  const raw = template.value?.uploaded_at
  return raw ? raw.replace('T', ' ').slice(0, 16) : null
})
</script>

<template>
  <div class="rounded-xl border border-gray-200 dark:border-white/10 p-4 space-y-3">
    <div class="flex items-start justify-between gap-2">
      <div class="grid md:grid-cols-3 gap-3 flex-1 min-w-0">
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel (Überschrift)</label>
          <input :value="doc.title" :disabled="readonly" class="afi w-full"
                 placeholder="z. B. Arbeitsvertrag"
                 @input="emit('update', { title: ($event.target as HTMLInputElement).value })" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Dateiname (Export)</label>
          <input :value="doc.filename" :disabled="readonly" class="afi w-full font-mono text-sm"
                 placeholder="z. B. Arbeitsvertrag_Nachname"
                 @input="emit('update', { filename: ($event.target as HTMLInputElement).value })" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Schlüssel</label>
          <input :value="doc.key" :disabled="readonly || template?.exists" class="afi w-full font-mono text-sm"
                 placeholder="z. B. dokument"
                 @change="emit('update', { key: ($event.target as HTMLInputElement).value })" />
          <p v-if="template?.exists" class="text-[11px] text-gray-400 mt-1">
            Bei hochgeladener Vorlage gesperrt (die Verknüpfung hängt am Schlüssel).
          </p>
        </div>
      </div>
      <button v-if="!readonly && canRemove" class="text-gray-400 hover:text-red-500 px-1 shrink-0"
              title="Dokument entfernen" @click="emit('remove')">✕</button>
    </div>

    <!-- Vorlagen-Quelle: feste Hochlade-Vorlage ODER firmenabhängig (nach Name). -->
    <div v-if="!readonly" class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-gray-500 dark:text-gray-400">Vorlage:</span>
      <button type="button" @click="setCompanyMode(false)"
              class="text-xs px-2.5 py-1 rounded-lg transition"
              :class="!companyMode ? 'bg-[#3EAAB8] text-white' : 'bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300'">
        Hochladen (fest)
      </button>
      <button type="button" @click="setCompanyMode(true)"
              class="text-xs px-2.5 py-1 rounded-lg transition"
              :class="companyMode ? 'bg-[#3EAAB8] text-white' : 'bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300'">
        Firmen-Vorlage (nach Name)
      </button>
    </div>

    <!-- HOCHLADE-MODUS: feste Vorlage je (Prozess, Phase, Dokument). -->
    <template v-if="!companyMode">
      <p v-if="!templateReady" class="text-sm text-amber-600 dark:text-amber-400">
        Bitte den Prozess speichern und der Phase einen Schlüssel geben – danach
        lässt sich die Vorlage hochladen.
      </p>
      <template v-else>
        <input ref="fileInput" type="file" accept=".docx,.pdf" class="hidden" @change="onFilePicked" />
        <p v-if="tplLoading" class="text-sm text-gray-400 italic">Vorlage wird geladen …</p>
        <div v-else-if="!template?.exists"
             class="rounded-xl border border-dashed border-gray-300 dark:border-white/15 px-4 py-6 text-center">
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">Noch keine Vorlage hinterlegt.</p>
          <button v-if="!readonly" class="btn-primary text-sm" :disabled="tplBusy" @click="pickFile">
            {{ tplBusy ? 'Lädt hoch …' : '.docx- oder PDF-Vorlage hochladen' }}
          </button>
        </div>
        <div v-else class="flex items-center justify-between gap-3 rounded-xl border border-gray-200
                    dark:border-white/10 px-4 py-3">
          <div class="min-w-0">
            <p class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
              {{ template.filename }}
              <span class="ml-1 text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5
                           bg-gray-100 dark:bg-white/10 text-gray-500 dark:text-gray-300">{{ formatLabel }}</span>
            </p>
            <p class="text-[11px] text-gray-400">
              {{ placeholders.length }} Platzhalter · {{ mappedCount }} zugeordnet
              <span v-if="uploadedAtLabel"> · {{ uploadedAtLabel }}</span>
              <span v-if="template.uploaded_by"> · {{ template.uploaded_by }}</span>
            </p>
          </div>
          <div v-if="!readonly" class="flex items-center gap-2 shrink-0">
            <button class="btn-secondary text-xs py-1" :disabled="tplBusy" @click="pickFile">Ersetzen</button>
            <button class="text-gray-400 hover:text-red-500 px-1" :disabled="tplBusy"
                    title="Vorlage entfernen" @click="removeTemplate">✕</button>
          </div>
        </div>
      </template>
    </template>

    <!-- FIRMEN-MODUS: die Datei kommt je gewählter Firma aus den Firmen-Einstellungen,
         gewählt wird nur der Vorlagen-TYP. -->
    <div v-else class="space-y-2 rounded-xl border border-gray-200 dark:border-white/10 p-3">
      <div class="grid md:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Firmen-Feld</label>
          <select :value="doc.companyField ?? ''" :disabled="readonly" class="afi w-full text-sm"
                  @change="emit('update', { companyField: ($event.target as HTMLSelectElement).value })">
            <option value="">— Feld mit der Firma wählen —</option>
            <option v-for="f in companyFields" :key="f.key" :value="f.key">{{ f.label }}</option>
          </select>
          <p v-if="!companyFields.length" class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
            Kein Feld vom Typ „Firma“ im Prozess – zuerst anlegen.
          </p>
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Vorlagen-Typ</label>
          <select :value="doc.companyTemplate ?? ''" :disabled="readonly" class="afi w-full text-sm"
                  @change="emit('update', { companyTemplate: ($event.target as HTMLSelectElement).value })">
            <option value="">— Vorlagen-Typ wählen —</option>
            <option v-for="l in labels" :key="l.name" :value="l.name">{{ l.name }}</option>
            <!-- Gespeicherter, aber nicht mehr vorhandener Typ bleibt sichtbar/korrigierbar. -->
            <option v-if="typeUnknown" :value="doc.companyTemplate">{{ doc.companyTemplate }} (nicht mehr vorhanden)</option>
          </select>
          <p v-if="!labels.length" class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
            Keine Vorlagen-Typen angelegt – unter Einstellungen → Vorlagen-Typen erstellen.
          </p>
          <p v-else-if="typeUnknown" class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
            Diesen Vorlagen-Typ gibt es nicht mehr – bitte neu wählen.
          </p>
          <p v-else-if="doc.companyTemplate && !typeLabel?.placeholders" class="text-[11px] text-gray-400 mt-1">
            Für diesen Typ ist noch keine Firmen-Vorlage hochgeladen – Platzhalter erscheinen nach dem ersten Upload.
          </p>
        </div>
      </div>
      <p v-if="companyHalfSet" class="text-[11px] text-amber-600 dark:text-amber-400">
        Firmen-Feld und Vorlagen-Typ müssen beide gesetzt sein.
      </p>
      <p class="text-[11px] text-gray-400">
        Die .docx/PDF kommt beim Erzeugen aus den Einstellungen der gewählten Firma (Vorlage dieses Typs).
        Alle Firmen-Vorlagen eines Typs haben dieselben {{ PH_HINT }}-Platzhalter; die Zuordnung unten gilt
        für alle Firmen.
      </p>
    </div>

    <!-- Zuordnung + bedingte Passagen: in beiden Modi, sobald Marker bekannt sind. -->
    <div v-if="companyMode || template?.exists" class="space-y-3">
        <div v-if="placeholders.length" class="space-y-2">
          <label class="block text-xs text-gray-500 dark:text-gray-400">Platzhalter zuordnen</label>
          <div v-for="m in placeholders" :key="m" class="space-y-1">
            <div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-2">
              <span class="font-mono text-xs text-gray-700 dark:text-gray-200 truncate"
                    :title="m">{{ markerLabel(m) }}</span>
              <select :value="bindingFor(m)" :disabled="readonly" class="afi w-full text-sm"
                      @change="setBinding(m, ($event.target as HTMLSelectElement).value)">
                <option value="">— manuell (nachfüllen) —</option>
                <option :value="TODAY_BINDING">Aktuelles Datum (heute)</option>
                <option v-for="f in bindableFields" :key="f.key" :value="f.key">{{ f.label }}</option>
              </select>
            </div>
            <div v-if="isFieldBinding(m)"
                 class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-2">
              <span></span>
              <label class="flex items-center gap-2 text-[11px] text-gray-400">
                Rechen-Versatz
                <input type="number" :value="bindingOffset(m)" :disabled="readonly"
                       class="afi w-24 text-sm" placeholder="z. B. -20"
                       @input="setOffset(m, ($event.target as HTMLInputElement).value)" />
              </label>
            </div>
          </div>
        </div>
        <p v-else class="text-sm text-gray-400 italic">
          <template v-if="companyMode">
            Noch keine Marker bekannt – oben einen Vorlagen-Typ wählen und für diesen Typ
            (in einer Firma) eine Vorlage hochladen.
          </template>
          <template v-else>In dieser Vorlage wurden keine {{ PH_HINT }}-Platzhalter gefunden.</template>
        </p>

        <!-- Bedingte Passagen: {{#if:NAME}} … {{/if}} -->
        <div class="pt-1 space-y-2">
          <div class="flex items-center justify-between gap-2">
            <label class="block text-xs text-gray-500 dark:text-gray-400">
              Bedingte Passagen <span class="font-mono">{{ ifHint }}</span>
            </label>
            <button v-if="!readonly" type="button" class="text-xs text-[#3EAAB8] hover:underline"
                    @click="addSection">+ Passus</button>
          </div>
          <p v-if="!sectionEntries.length" class="text-[11px] text-gray-400">
            Ein Passus mit passendem Namen bleibt nur im Dokument, wenn seine Bedingung erfüllt ist
            (sonst wird der Block entfernt).
          </p>
          <div v-for="[name, cond] in sectionEntries" :key="name"
               class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-2">
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-gray-400 whitespace-nowrap">Name</span>
              <input :value="name" :disabled="readonly" class="afi !py-1 !px-2 text-sm font-mono flex-1"
                     placeholder="z. B. firmenwagen"
                     @change="renameSection(name, ($event.target as HTMLInputElement).value)" />
              <button v-if="!readonly" type="button" class="text-gray-400 hover:text-red-500 px-1"
                      title="Passus entfernen" @click="removeSection(name)">✕</button>
            </div>
            <div class="text-[11px] text-gray-500">Passus einblenden, wenn:</div>
            <ConditionEditor :model-value="cond" :field-keys="(catalog ?? []).map((f) => f.key)"
                             @update:model-value="setSectionCond(name, $event as Condition | null)" />
          </div>
        </div>
      </div>
  </div>
</template>
