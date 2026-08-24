<script setup lang="ts">
/**
 * Dokument-Phase (view='document') – ZWEI Modi, die sich aus der Definition
 * ergeben (kein Zugriff auf den Manage-Endpunkt nötig):
 *
 *  1. .docx-VORLAGE (Standard, `document.templateHtml` leer): eine im Editor
 *     hochgeladene Word-Datei ist die Vorlage. Beim Export füllt der SERVER die
 *     {{marker}} aus den Auftragswerten (Zuordnung = `document.bindings`) und
 *     lässt alles andere im Dokument unverändert. Kein Inline-Editor – die Datei
 *     kommt fertig zurück; übrige Lücken füllt Sekretariat GL in Word nach.
 *
 *  2. HTML-VORLAGE (Alt-Weg, `document.templateHtml` gesetzt): eine HTML-Vorlage
 *     mit {{feld.key}} wird clientseitig vorausgefüllt, inline bearbeitet und der
 *     Stand serverseitig nach .docx gewandelt.
 *
 * Sicherheit (nur HTML-Modus): die VORLAGE ist admin-verfasst, die WERTE stammen
 * aus Nutzereingaben und werden vor dem innerHTML escaped.
 */
import { computed, onMounted, ref, watch } from 'vue'
import type { OptionSources, PhaseDef, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import { renderMailTemplate } from '@/lib/mailTemplate'
import { fieldValueText } from '@/lib/processFieldFormat'
import { exportTicketDocument } from '@/api/processTickets'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'
import DocumentEditorModal from '@/components/process/form/DocumentEditorModal.vue'

const props = defineProps<{
  definition: ProcessDefinition
  ticket: ProcessTicketOut
  phase: PhaseDef
  sources?: OptionSources
  /** Leseansicht: Dokument zeigen + exportieren, aber nicht inline bearbeiten. */
  readonly?: boolean
}>()

const { showToast } = useToast()

const spec = computed(() => props.phase.document)
const busy = ref(false)
const editor = ref<HTMLElement | null>(null)

const catalog = computed(() => new Map(props.definition.fields.map((f) => [f.key, f])))

/** .docx-Modus, sobald KEINE HTML-Vorlage hinterlegt ist (der Normalfall). */
const isHtml = computed(() => !!spec.value?.templateHtml?.trim())

/** Roh-Text eines Platzhalters: {{title}}/{{id}} plus jedes Katalog-Feld. */
function rawValue(token: string): string {
  if (token === 'title') return String(props.ticket.title ?? '')
  if (token === 'id') return String(props.ticket.id ?? '')
  const f = catalog.value.get(token)
  if (!f) return ''
  const text = fieldValueText(f, (props.ticket.values ?? {})[token], props.sources)
  return text === '—' ? '' : text   // leeres Feld → leere Stelle, kein Strich
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const dateiname = computed(() =>
  renderMailTemplate(spec.value?.filename ?? 'Dokument', rawValue).trim() || 'Dokument')

/** Datei herunterladen (Blob → temporärer Link). */
function download(blob: Blob) {
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = `${dateiname.value}.docx`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

// ── .docx-Modus ──────────────────────────────────────────────────────────────

/** Was automatisch aus dem Auftrag eingesetzt wird (aus `document.bindings`). */
const boundPreview = computed(() =>
  Object.entries(spec.value?.bindings ?? {}).map(([marker, fieldKey]) => {
    const f = catalog.value.get(fieldKey)
    return { marker, label: f?.label || fieldKey, value: rawValue(fieldKey) }
  }))

/** Editor-Modal: ganzes .docx previewen, Felder ausfüllen/korrigieren, exportieren. */
const showEditor = ref(false)

// ── HTML-Modus (Alt-Weg) ─────────────────────────────────────────────────────

const gefuelltHtml = computed(() =>
  renderMailTemplate(spec.value?.templateHtml ?? '', (t) => esc(rawValue(t))))

/** Editor-Inhalt EINMAL setzen – nicht reaktiv (sonst überschriebe jede Ticket-
 *  Aktualisierung die Anpassungen des Bearbeiters). Ticket-Wechsel füllt neu. */
function fuelle() {
  if (editor.value) editor.value.innerHTML = gefuelltHtml.value
}
onMounted(() => { if (isHtml.value) fuelle() })
watch(() => props.ticket.id, () => { if (isHtml.value) fuelle() })

async function htmlExport() {
  const html = editor.value?.innerHTML ?? gefuelltHtml.value
  busy.value = true
  try {
    download(await exportTicketDocument(props.ticket.id, { html, filename: dateiname.value }))
  } catch (e) {
    showToast(errorMessage(e, 'Word-Export fehlgeschlagen'), false)
  } finally {
    busy.value = false
  }
}

function drucken() {
  const html = editor.value?.innerHTML ?? gefuelltHtml.value
  const w = window.open('', '_blank')
  if (!w) { showToast('Bitte Pop-ups erlauben, um zu drucken', false); return }
  w.document.write('<!doctype html><html><head><meta charset="utf-8">'
    + `<title>${dateiname.value}</title>`
    + '<style>body{font-family:Arial,Helvetica,sans-serif;max-width:800px;margin:2rem auto;'
    + 'padding:0 1rem;line-height:1.55;color:#111}h1{font-size:1.5rem}h2{font-size:1.25rem}'
    + 'h3{font-size:1.1rem}</style></head><body>' + html + '</body></html>')
  w.document.close()
  w.focus()
  w.print()
}
</script>

<template>
  <div class="card-section">
    <div class="flex items-center justify-between gap-3 flex-wrap mb-3">
      <h3 class="section-title mb-0">{{ spec?.title || 'Dokument' }}</h3>
      <div class="flex items-center gap-2">
        <!-- HTML-Modus: Zurücksetzen / Drucken / Word -->
        <template v-if="isHtml">
          <button v-if="!readonly" @click="fuelle" :disabled="busy" class="btn-secondary text-xs">
            Zurücksetzen
          </button>
          <button @click="drucken" :disabled="busy" class="btn-secondary text-xs">
            Drucken / PDF
          </button>
          <button v-if="!readonly" @click="htmlExport" :disabled="busy"
                  class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                         disabled:opacity-40 transition">
            {{ busy ? 'Wird erzeugt…' : 'Als Word exportieren' }}
          </button>
        </template>
        <!-- .docx-Modus: Editor-Modal öffnen (Vorschau + Felder + Word/PDF).
             Bewusst OHNE readonly-Guard: exportieren darf jede:r mit Vollsicht;
             wer kein Recht hat, sieht im Modal die Server-Meldung (403/keine
             Vorlage). -->
        <button v-else @click="showEditor = true"
                class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                       disabled:opacity-40 transition">
          Ausfüllen &amp; exportieren
        </button>
      </div>
    </div>

    <!-- .docx-Modus: Zusammenfassung statt Inline-Editor -->
    <template v-if="!isHtml">
      <p class="text-xs text-gray-400 mb-3">
        „Ausfüllen &amp; exportieren" öffnet die Vorschau des ganzen Dokuments:
        zugeordnete Felder sind vorausgefüllt, offene Felder lassen sich dort direkt
        eintragen und als Word oder PDF exportieren. Die Übersicht unten zeigt die
        automatisch eingesetzten Felder.
      </p>
      <div v-if="boundPreview.length"
           class="rounded-xl border border-gray-200 dark:border-white/10 divide-y
                  divide-gray-100 dark:divide-white/5">
        <div v-for="b in boundPreview" :key="b.marker"
             class="flex items-baseline justify-between gap-4 px-4 py-2 text-sm">
          <span class="text-gray-500 dark:text-gray-400 shrink-0">{{ b.label }}</span>
          <span class="text-gray-900 dark:text-gray-100 text-right truncate"
                :class="{ 'italic text-gray-400 dark:text-gray-500': !b.value }">
            {{ b.value || '(leer – in Word nachfüllen)' }}
          </span>
        </div>
      </div>
      <p v-else class="text-sm text-gray-400 italic">
        Für diese Phase ist noch keine automatische Feld-Zuordnung hinterlegt – die
        Vorlage wird unverändert exportiert.
      </p>
    </template>

    <!-- HTML-Modus: Inline-Editor -->
    <template v-else>
      <p class="text-xs text-gray-400 mb-2">
        <template v-if="readonly">Vorschau mit den Auftragsdaten. Bearbeiten und Word-Export
          über die Bearbeitungsansicht.</template>
        <template v-else>Vorschau mit den Auftragsdaten – direkt im Text anpassbar. Der Export
          nimmt genau diesen Stand.</template>
      </p>
      <div ref="editor" :contenteditable="!readonly" spellcheck="false"
           class="doc-editor rounded-xl border border-gray-200 dark:border-white/10
                  bg-white dark:bg-[#1A2130] text-gray-900 dark:text-gray-100 p-6 min-h-[320px]
                  text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
    </template>

    <DocumentEditorModal v-if="showEditor" :ticket-id="ticket.id" @close="showEditor = false" />
  </div>
</template>

<!-- Nicht scoped: die Regeln müssen auf den per innerHTML eingesetzten
     Dokument-Inhalt greifen (Tailwind-Preflight setzt Überschriften sonst platt). -->
<style>
.doc-editor h1 { font-size: 1.5rem; font-weight: 700; margin: 0.6em 0 0.3em; }
.doc-editor h2 { font-size: 1.25rem; font-weight: 700; margin: 0.6em 0 0.3em; }
.doc-editor h3 { font-size: 1.1rem; font-weight: 600; margin: 0.5em 0 0.3em; }
.doc-editor p { margin: 0.45em 0; }
.doc-editor ul { list-style: disc; padding-left: 1.5em; margin: 0.45em 0; }
.doc-editor ol { list-style: decimal; padding-left: 1.5em; margin: 0.45em 0; }
</style>
