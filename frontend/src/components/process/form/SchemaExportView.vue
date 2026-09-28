<script setup lang="ts">
/**
 * Ansicht der Phasen-Darstellung 'export': eine lesbare Zusammenfassung des
 * Auftrags plus die Schaltfläche „PDF exportieren".
 *
 * Bewusst prozessunabhängig – der Nachfolger des hartcodierten
 * HotelbuchungExportPanel. Auf dem Bildschirm zeigt SchemaReadonlyView die
 * Werte, im PDF zeichnet lib/processPdf.ts dieselben Abschnitte, Breiten und
 * Reihenfolgen (beide gehen über resolveLayout).
 *
 * jspdf hängt NICHT an dieser Komponente: es wird erst im Klick-Handler
 * nachgeladen (siehe exportProcessPdf), sonst zöge die Bibliothek ~129 kB gzip
 * in das Chunk jedes Prozess-Auftrags.
 */
import { computed, onMounted, ref, watch } from 'vue'
import type {
  OptionSources, PhaseDef, ProcessDefinition, ProcessTicketOut,
} from '@/types/process'
import type { SimViewer } from '@/lib/processSim'
import { exportProcessPdf, formatTimestamp } from '@/lib/processPdf'
import type { ExportMeta } from '@/lib/processPdf'
import { listAttachments } from '@/api/processAttachments'
import SchemaReadonlyView from './SchemaReadonlyView.vue'

const props = defineProps<{
  definition: ProcessDefinition
  ticket: ProcessTicketOut
  /** Die Export-Phase; ohne sie bleiben nur die erfassten Werte übrig. */
  phase?: PhaseDef | null
  viewer: SimViewer
  sources?: OptionSources
  /**
   * Dateinamen je Anhang-Feld. Ohne Angabe holt die Komponente sie selbst –
   * scheitert auch das, sagt das PDF ehrlich, dass keine Namen vorliegen.
   */
  attachments?: Record<string, string[]>
}>()

const emit = defineEmits<{ exported: [fileName: string]; failed: [message: string] }>()

const exporting = ref(false)
const fehler = ref<string | null>(null)

const meta = computed<ExportMeta>(() => ({
  processName: props.definition?.name || 'Auftrag',
  ticketTitle: props.ticket?.title || '',
  ticketNumber: props.ticket?.id ? `#${props.ticket.id}` : null,
  ownerName: props.ticket?.owner_name ?? null,
  createdAt: props.ticket?.created_at ?? null,
  phaseLabel: props.phase?.label || props.ticket?.current_phase_label || null,
}))

// ── Anhänge ──────────────────────────────────────────────────────────────────

/**
 * Anhänge stehen NICHT in `values`, sondern in der Datei-Ablage des Auftrags.
 * Ohne diesen Ladeschritt bliebe im PDF nur der Hinweis, dass keine Namen
 * vorliegen – weglassen wäre die unehrliche Variante.
 */
const attachmentFields = computed(() =>
  (props.definition?.fields ?? []).filter((f) => f.widget === 'attachment').map((f) => f.key))

/** null = nicht ermittelt (nicht geladen oder Abruf fehlgeschlagen). */
const geladeneAnhaenge = ref<Record<string, string[]> | null>(null)

async function ladeAnhaenge() {
  geladeneAnhaenge.value = null
  if (props.attachments || !attachmentFields.value.length || !props.ticket?.id) return
  try {
    const rows = await listAttachments(props.ticket.id)
    const map: Record<string, string[]> = {}
    for (const key of attachmentFields.value) map[key] = []
    for (const r of rows) {
      if (!r.field_key || !(r.field_key in map)) continue
      map[r.field_key].push(r.original_filename)
    }
    geladeneAnhaenge.value = map
  } catch {
    // Kein Abbruch: das PDF weist selbst darauf hin, dass Namen fehlen.
    geladeneAnhaenge.value = null
  }
}

onMounted(ladeAnhaenge)
watch(() => props.ticket?.id, ladeAnhaenge)

// ── Export ───────────────────────────────────────────────────────────────────

async function exportPdf() {
  if (exporting.value) return
  exporting.value = true
  fehler.value = null
  try {
    const name = await exportProcessPdf({
      definition: props.definition,
      phase: props.phase ?? null,
      values: props.ticket?.values ?? {},
      viewer: props.viewer,
      sources: props.sources,
      meta: meta.value,
      attachments: props.attachments ?? geladeneAnhaenge.value ?? undefined,
    })
    emit('exported', name)
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'PDF konnte nicht erzeugt werden'
    fehler.value = msg
    emit('failed', msg)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <!-- Kopfdaten des Auftrags + Export -->
    <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                rounded-2xl shadow-sm p-5 flex items-center justify-between gap-4 flex-wrap">
      <div class="min-w-0">
        <p class="text-sm font-semibold text-gray-900 dark:text-white truncate">
          {{ meta.processName }}<span v-if="meta.phaseLabel"> – {{ meta.phaseLabel }}</span>
        </p>
        <p class="text-xs text-gray-400 mt-0.5">
          <span v-if="meta.ticketNumber">{{ meta.ticketNumber }} · </span>
          {{ meta.ticketTitle || '—' }}
        </p>
        <p class="text-xs text-gray-400 mt-0.5">
          Erstellt von {{ meta.ownerName || '—' }} · {{ formatTimestamp(meta.createdAt) }}
        </p>
      </div>

      <button
        type="button" @click="exportPdf" :disabled="exporting"
        class="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium
               bg-[#3EAAB8] hover:bg-[#2B7D89] text-white disabled:opacity-60 transition
               flex-shrink-0"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"
             stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round"
                d="M12 10v6m0 0l-3-3m3 3l3-3M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
        </svg>
        {{ exporting ? 'Erzeuge PDF…' : 'PDF exportieren' }}
      </button>
    </div>

    <p v-if="fehler" class="text-sm text-red-600 dark:text-red-400 px-1">{{ fehler }}</p>

    <!-- Bildschirm-Zusammenfassung: dieselben Abschnitte, die auch ins PDF gehen -->
    <SchemaReadonlyView
      :definition="definition"
      :values="ticket.values || {}"
      :viewer="viewer"
      :sources="sources"
      :phase="phase ?? null"
    />
  </div>
</template>
