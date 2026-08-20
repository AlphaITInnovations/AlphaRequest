<script setup lang="ts">
/**
 * Dokument-Phase (view='document'): eine HTML-Vorlage mit {{feld.key}}-
 * Platzhaltern wird mit den Auftragsdaten vorausgefüllt, in einem Inline-Editor
 * (contenteditable) angezeigt und als Word (.docx) exportiert (Drucken → PDF
 * geht über den Browser). Genutzt z. B. für den Arbeitsvertrag.
 *
 * Sicherheit: die VORLAGE ist admin-verfasst (vertrauenswürdiges HTML), die
 * eingesetzten WERTE stammen aus Nutzereingaben und werden deshalb escaped, bevor
 * sie ins innerHTML gehen. Der Word-Export escaped serverseitig ohnehin erneut.
 */
import { computed, onMounted, ref, watch } from 'vue'
import type { OptionSources, PhaseDef, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import { renderMailTemplate } from '@/lib/mailTemplate'
import { fieldValueText } from '@/lib/processFieldFormat'
import { exportTicketDocument } from '@/api/processTickets'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'

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

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Platzhalter-Wert (escaped): {{title}}/{{id}} plus jedes Katalog-Feld. */
function resolve(token: string): string {
  if (token === 'title') return esc(String(props.ticket.title ?? ''))
  if (token === 'id') return esc(String(props.ticket.id ?? ''))
  const f = catalog.value.get(token)
  if (!f) return ''
  const text = fieldValueText(f, (props.ticket.values ?? {})[token], props.sources)
  return esc(text === '—' ? '' : text)   // leeres Feld → leere Stelle, kein Strich
}

const gefuelltHtml = computed(() => renderMailTemplate(spec.value?.templateHtml ?? '', resolve))
const dateiname = computed(() =>
  renderMailTemplate(spec.value?.filename ?? 'Dokument', resolve).trim() || 'Dokument')

/** Editor-Inhalt EINMAL setzen – nicht reaktiv (sonst würde jede Ticket-Aktualisierung
 *  die Anpassungen des Bearbeiters überschreiben). Ticket-Wechsel füllt neu. */
function fuelle() {
  if (editor.value) editor.value.innerHTML = gefuelltHtml.value
}
onMounted(fuelle)
watch(() => props.ticket.id, fuelle)

async function wordExport() {
  const html = editor.value?.innerHTML ?? gefuelltHtml.value
  busy.value = true
  let url: string | null = null
  try {
    const blob = await exportTicketDocument(props.ticket.id, html, dateiname.value)
    url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${dateiname.value}.docx`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch (e) {
    showToast(errorMessage(e, 'Word-Export fehlgeschlagen'), false)
  } finally {
    if (url) { const u = url; setTimeout(() => URL.revokeObjectURL(u), 0) }
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
        <button v-if="!readonly" @click="fuelle" :disabled="busy" class="btn-secondary text-xs">
          Zurücksetzen
        </button>
        <button @click="drucken" :disabled="busy" class="btn-secondary text-xs">
          Drucken / PDF
        </button>
        <button v-if="!readonly" @click="wordExport" :disabled="busy"
                class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                       disabled:opacity-40 transition">
          {{ busy ? 'Wird erzeugt…' : 'Als Word exportieren' }}
        </button>
      </div>
    </div>
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
