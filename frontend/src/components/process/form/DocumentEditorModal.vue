<script setup lang="ts">
/**
 * Editor-Modal für die Dokument-Phase (.docx-Vorlage).
 *
 * Links ein Formular je {{marker}} der Vorlage (manuelle Felder ausfüllen,
 * automatisch befüllte notfalls korrigieren), rechts eine LIVE-Vorschau des
 * ganzen gefüllten .docx (docx-preview rendert die vom Server gefüllte Datei).
 * Export als Word (.docx, Server-Fill) oder PDF (client-seitig aus der Vorschau).
 *
 * Die Vorlage bleibt im Backend mit ihren {{}}; hier reisen nur die Marker-Werte
 * als `overrides` mit – die Definition/bindings werden NICHT verändert.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  getDocumentFields, exportTicketDocument, type DocumentField,
} from '@/api/processTickets'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'

const props = defineProps<{ ticketId: number }>()
const emit = defineEmits<{ close: [] }>()

// Doppelte geschweifte Klammern nicht direkt ins <template> (Vue liest sie als
// Interpolation) – als Script-Konstante einsetzen.
const PH_HINT = '{{…}}'

const { showToast } = useToast()

const loading = ref(true)
const loadError = ref<string | null>(null)
const fields = ref<DocumentField[]>([])
const filename = ref('Dokument')
const docTitle = ref<string | null>(null)

const previewEl = ref<HTMLElement | null>(null)
const previewBusy = ref(false)
const exporting = ref(false)

const manualFields = computed(() => fields.value.filter((f) => !f.bound))
const autoFields = computed(() => fields.value.filter((f) => f.bound))

function overrides(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of fields.value) out[f.name] = f.value
  return out
}

// ── Laden + Vorschau ─────────────────────────────────────────────────────────

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const data = await getDocumentFields(props.ticketId)
    fields.value = data.markers.map((m) => ({ ...m }))
    filename.value = data.filename || 'Dokument'
    docTitle.value = data.title
    await nextTick()
    await renderPreview()
  } catch (e) {
    loadError.value = errorMessage(e, 'Die Vorlage konnte nicht geladen werden.')
  } finally {
    loading.value = false
  }
}

// „Latest-Wins": nur der zuletzt gestartete Render darf das DOM/den Zustand
// schreiben. Ohne das könnte ein langsamer älterer Server-Fill nach einem
// schnelleren neueren zurückkommen und die Vorschau auf einen VERALTETEN Stand
// überschreiben (out-of-order).
let renderSeq = 0

/** Aktuellen Stand serverseitig füllen und die .docx in die Vorschau rendern.
 *  Gibt true zurück, wenn DIESER (der neueste) Render erfolgreich gerendert hat. */
async function renderPreview(): Promise<boolean> {
  const host = previewEl.value
  if (!host) return false
  const seq = ++renderSeq
  previewBusy.value = true
  try {
    const blob = await exportTicketDocument(props.ticketId,
      { overrides: overrides(), filename: filename.value })
    const { renderAsync } = await import('docx-preview')
    if (seq !== renderSeq) return false          // ein neuerer Render hat übernommen
    host.innerHTML = ''
    await renderAsync(blob, host, undefined,
      { inWrapper: true, breakPages: true, className: 'docx' })
    return seq === renderSeq
  } catch (e) {
    if (seq === renderSeq) showToast(errorMessage(e, 'Vorschau fehlgeschlagen.'), false)
    return false
  } finally {
    if (seq === renderSeq) previewBusy.value = false
  }
}

let timer: ReturnType<typeof setTimeout> | null = null
function schedulePreview() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(renderPreview, 500)   // Tipp-Pause abwarten, nicht pro Anschlag
}

// ── Export ───────────────────────────────────────────────────────────────────

function triggerDownload(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

async function exportDocx() {
  exporting.value = true
  try {
    const blob = await exportTicketDocument(props.ticketId,
      { overrides: overrides(), filename: filename.value })
    triggerDownload(blob, `${filename.value}.docx`)
  } catch (e) {
    showToast(errorMessage(e, 'Word-Export fehlgeschlagen.'), false)
  } finally {
    exporting.value = false
  }
}

async function exportPdf() {
  exporting.value = true
  try {
    if (timer) { clearTimeout(timer); timer = null }
    // Re-Render MUSS gelingen – sonst würde ein veraltetes/leeres PDF gespeichert.
    if (!await renderPreview()) {
      showToast('Vorschau nicht bereit – PDF nicht erzeugt.', false)
      return
    }
    const host = previewEl.value
    const pages = host
      ? Array.from(host.querySelectorAll<HTMLElement>('section.docx')) : []
    if (!pages.length) { showToast('Kein Dokument zum Exportieren.', false); return }

    const [{ jsPDF }, h2c] = await Promise.all([import('jspdf'), import('html2canvas')])
    const html2canvas = h2c.default
    const pdf = new jsPDF({ unit: 'pt', format: 'a4' })
    const pw = pdf.internal.pageSize.getWidth()
    const ph = pdf.internal.pageSize.getHeight()
    // Jede docx-Seite EINZELN rastern: umgeht das Canvas-Größenlimit langer
    // Dokumente und hält je docx-Seite genau eine PDF-Seite (keine driftenden
    // Umbrüche oder doppelten Ränder wie beim Rastern des ganzen Wrappers).
    for (let i = 0; i < pages.length; i++) {
      const canvas = await html2canvas(pages[i],
        { scale: 2, backgroundColor: '#ffffff', useCORS: true })
      const ratio = Math.min(pw / canvas.width, ph / canvas.height)
      const w = canvas.width * ratio
      const h = canvas.height * ratio
      if (i > 0) pdf.addPage()
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', (pw - w) / 2, 0, w, h)
    }
    pdf.save(`${filename.value}.pdf`)
  } catch (e) {
    showToast(errorMessage(e, 'PDF-Export fehlgeschlagen.'), false)
  } finally {
    exporting.value = false
  }
}

// ── Schließen ──────────────────────────────────────────────────────────────

function close() { emit('close') }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }

onMounted(() => { document.addEventListener('keydown', onKey); load() })
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
         @click.self="close">
      <div class="flex w-full max-w-6xl h-[90vh] flex-col overflow-hidden rounded-2xl
                  bg-white dark:bg-[#141a26] shadow-2xl">
        <!-- Kopf -->
        <div class="flex items-center justify-between gap-3 border-b border-gray-200
                    dark:border-white/10 px-5 py-3">
          <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100 truncate">
            {{ docTitle || 'Dokument' }} ausfüllen &amp; exportieren
          </h3>
          <button class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl leading-none px-1"
                  title="Schließen" @click="close">✕</button>
        </div>

        <!-- Ladefehler (z. B. keine Vorlage hinterlegt) -->
        <div v-if="loadError" class="flex flex-1 items-center justify-center p-8 text-center">
          <p class="text-sm text-gray-600 dark:text-gray-300 max-w-md">{{ loadError }}</p>
        </div>

        <!-- Körper: Formular + Vorschau -->
        <div v-else class="flex flex-1 min-h-0">
          <!-- Formular -->
          <div class="w-80 shrink-0 overflow-y-auto border-r border-gray-200 dark:border-white/10 p-4 space-y-5">
            <p v-if="loading" class="text-sm text-gray-400 italic">Wird geladen …</p>
            <template v-else>
              <section v-if="manualFields.length">
                <h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                  Manuell auszufüllen
                </h4>
                <div class="space-y-3">
                  <div v-for="f in manualFields" :key="f.name">
                    <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">{{ f.label }}</label>
                    <input v-model="f.value" class="afi w-full text-sm" @input="schedulePreview" />
                  </div>
                </div>
              </section>

              <section v-if="autoFields.length">
                <h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                  Automatisch (korrigierbar)
                </h4>
                <div class="space-y-3">
                  <div v-for="f in autoFields" :key="f.name">
                    <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">{{ f.label }}</label>
                    <input v-model="f.value" class="afi w-full text-sm" @input="schedulePreview" />
                  </div>
                </div>
              </section>

              <p v-if="!fields.length" class="text-sm text-gray-400 italic">
                Diese Vorlage hat keine {{ PH_HINT }}-Felder.
              </p>
            </template>
          </div>

          <!-- Vorschau -->
          <div class="relative flex-1 overflow-auto bg-gray-100 dark:bg-[#0d1117] p-6">
            <div v-if="previewBusy"
                 class="absolute right-3 top-3 z-10 rounded-full bg-black/60 px-3 py-1 text-xs text-white">
              Vorschau aktualisiert …
            </div>
            <div ref="previewEl" class="docx-host mx-auto" />
          </div>
        </div>

        <!-- Fuß -->
        <div class="flex items-center justify-end gap-2 border-t border-gray-200 dark:border-white/10 px-5 py-3">
          <button class="btn-secondary text-sm" :disabled="exporting" @click="close">Abbrechen</button>
          <button class="btn-secondary text-sm" :disabled="loading || exporting || !!loadError"
                  @click="exportPdf">
            {{ exporting ? 'Erzeuge …' : 'Als PDF' }}
          </button>
          <button class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                         disabled:opacity-40 transition"
                  :disabled="loading || exporting || !!loadError" @click="exportDocx">
            Als Word (.docx)
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style>
/* docx-preview bringt eigene Seiten-Styles mit; wir geben dem Wrapper nur etwas
   Luft und eine dezente Seiten-Optik. Nicht scoped, weil der Inhalt per innerHTML
   von docx-preview kommt. */
.docx-host .docx-wrapper { background: transparent; padding: 0; }
.docx-host .docx-wrapper > section.docx {
  margin: 0 auto 1rem; box-shadow: 0 1px 6px rgba(0, 0, 0, 0.15); background: #fff;
}
</style>
