<script setup lang="ts">
/**
 * Editor-Modal für die Dokument-Phase (.docx-Vorlage).
 *
 * Links ein Formular je {{marker}} der Vorlage (manuelle Felder ausfüllen,
 * automatisch befüllte notfalls korrigieren), rechts eine LIVE-Vorschau des
 * ganzen gefüllten Dokuments als PDF. Das PDF erzeugt der Server originalgetreu
 * über LibreOffice (korrekte Seiten/Umbrüche wie in Word) – der Browser zeigt es
 * im eingebauten PDF-Viewer (Seiten, Zoom, Blättern nativ). Export als Word
 * (.docx) oder PDF – beides serverseitig, kein Client-Rendering.
 *
 * Die Vorlage bleibt im Backend mit ihren {{}}; nur die Marker-Werte reisen als
 * `overrides` mit – Definition/bindings bleiben unangetastet.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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

const previewBusy = ref(false)
const exporting = ref(false)
const pdfUrl = ref<string | null>(null)
let pdfBlob: Blob | null = null

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
    await refreshPreview()
  } catch (e) {
    loadError.value = errorMessage(e, 'Die Vorlage konnte nicht geladen werden.')
  } finally {
    loading.value = false
  }
}

// „Latest-Wins": nur die zuletzt gestartete Konvertierung darf die Vorschau
// setzen – sonst überschriebe ein langsamer älterer Lauf einen neueren (out-of-order).
let renderSeq = 0

/** Aktuellen Stand serverseitig zu PDF rendern und in die Vorschau setzen.
 *  Gibt true zurück, wenn DIESER (der neueste) Lauf erfolgreich war. */
async function refreshPreview(): Promise<boolean> {
  const seq = ++renderSeq
  previewBusy.value = true
  try {
    const blob = await exportTicketDocument(props.ticketId,
      { overrides: overrides(), filename: filename.value, format: 'pdf' })
    if (seq !== renderSeq) return false          // ein neuerer Lauf hat übernommen
    pdfBlob = blob
    const next = URL.createObjectURL(blob)
    const prev = pdfUrl.value
    pdfUrl.value = next
    if (prev) URL.revokeObjectURL(prev)
    return true
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
  timer = setTimeout(refreshPreview, 600)   // Tipp-Pause abwarten (Server-Konvertierung)
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

async function exportPdf() {
  exporting.value = true
  try {
    if (timer) { clearTimeout(timer); timer = null }
    // Aktuelles PDF sicherstellen (nutzt dieselbe Konvertierung wie die Vorschau).
    if (!await refreshPreview() || !pdfBlob) {
      showToast('PDF nicht bereit – bitte erneut versuchen.', false); return
    }
    triggerDownload(pdfBlob, `${filename.value}.pdf`)
  } catch (e) {
    showToast(errorMessage(e, 'PDF-Export fehlgeschlagen.'), false)
  } finally {
    exporting.value = false
  }
}

async function exportDocx() {
  exporting.value = true
  try {
    const blob = await exportTicketDocument(props.ticketId,
      { overrides: overrides(), filename: filename.value, format: 'docx' })
    triggerDownload(blob, `${filename.value}.docx`)
  } catch (e) {
    showToast(errorMessage(e, 'Word-Export fehlgeschlagen.'), false)
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
  if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
})
</script>

<template>
  <Teleport to="body">
    <!-- Bewusst KEIN Schließen bei Außenklick: nur X, „Abbrechen" oder Esc. -->
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div class="flex w-full max-w-7xl h-[92vh] flex-col overflow-hidden rounded-2xl
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

        <!-- Körper: Formular + PDF-Vorschau -->
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

          <!-- PDF-Vorschau (Browser-Viewer: Seiten, Blättern, Zoom) -->
          <div class="relative flex-1 min-h-0 bg-gray-100 dark:bg-[#0d1117]">
            <div v-if="previewBusy"
                 class="absolute right-4 top-3 z-10 rounded-full bg-black/60 px-3 py-1 text-xs text-white">
              Vorschau wird erstellt …
            </div>
            <iframe v-if="pdfUrl" :src="pdfUrl" title="Dokument-Vorschau"
                    class="h-full w-full border-0" />
            <div v-else class="flex h-full items-center justify-center p-8 text-sm text-gray-400">
              {{ loading ? 'Vorschau wird erstellt …' : 'Keine Vorschau verfügbar.' }}
            </div>
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
