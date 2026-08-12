<script setup lang="ts">
/**
 * Datei-Anhänge eines Prozess-Auftrags.
 *
 * Zwei Einsatzarten:
 *   - MIT `fieldKey`: die Dateien EINES Anhang-Feldes der Definition (widget
 *     'attachment') – so kann ein Prozess mehrere getrennte Ablagen haben
 *     (z. B. „Vertrag" und „Führerschein").
 *   - OHNE `fieldKey`: alle Dateien des Auftrags; Uploads landen als allgemeiner
 *     Anhang (field_key = NULL).
 *
 * `canEdit` steuert nur die OBERFLÄCHE. Verbindlich ist der Server: Upload und
 * Löschen setzen dort die Zuständigkeit für die aktuelle Phase voraus.
 * Diese Komponente wird bewusst NICHT selbst in eine View eingehängt.
 */
import { ref, onMounted, watch } from 'vue'
import {
  listAttachments, uploadAttachment, deleteAttachment, downloadUrl,
  type ProcessAttachment,
} from '@/api/processAttachments'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  ticketId: number
  fieldKey?: string | null
  canEdit?: boolean
}>(), { fieldKey: null, canEdit: false })

const { showToast } = useToast()

const items = ref<ProcessAttachment[]>([])
const loading = ref(false)
const uploading = ref(false)
const deleting = ref<number | null>(null)
const fehler = ref<string | null>(null)

/** Verstecktes <input type="file">; Klick kommt von den Buttons. */
const fileInput = ref<HTMLInputElement | null>(null)
/** Gesetzt = die nächste Auswahl ist eine neue VERSION dieser Datei-Familie. */
const versionOf = ref<string | null>(null)

function apiFehler(e: unknown, fallback: string): string {
  const err = e as { response?: { data?: { error?: { message?: string } } } }
  return err?.response?.data?.error?.message || fallback
}

// ── Laden ────────────────────────────────────────────────────────────────────

// Nur die jüngste Antwort gewinnt (Ticket-/Feldwechsel während des Ladens).
let reqId = 0
async function load() {
  const my = ++reqId
  loading.value = true
  fehler.value = null
  try {
    const rows = await listAttachments(props.ticketId, { fieldKey: props.fieldKey })
    if (my !== reqId) return
    items.value = rows
  } catch (e) {
    if (my !== reqId) return
    items.value = []
    fehler.value = apiFehler(e, 'Anhänge konnten nicht geladen werden')
  } finally {
    if (my === reqId) loading.value = false
  }
}

onMounted(load)
watch(() => [props.ticketId, props.fieldKey], load)

// ── Upload ───────────────────────────────────────────────────────────────────

function pickFile(familyId: string | null = null) {
  versionOf.value = familyId
  fileInput.value?.click()
}

async function onFileChosen(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  const familyId = versionOf.value
  // Input immer leeren: sonst löst dieselbe Datei beim zweiten Mal kein Event aus.
  input.value = ''
  versionOf.value = null
  if (!file) return

  uploading.value = true
  try {
    await uploadAttachment(props.ticketId, file, {
      fieldKey: props.fieldKey, familyId,
    })
    showToast(familyId ? `Neue Version von „${file.name}“ gespeichert`
                       : `„${file.name}“ hochgeladen`)
    await load()
  } catch (e) {
    showToast(apiFehler(e, 'Upload fehlgeschlagen'), false)
  } finally {
    uploading.value = false
  }
}

// ── Löschen ──────────────────────────────────────────────────────────────────

async function remove(a: ProcessAttachment) {
  if (!confirm(`Datei „${a.original_filename}“ wirklich löschen? `
               + 'Dies wird im Audit-Log festgehalten.')) return
  deleting.value = a.id
  try {
    await deleteAttachment(a.id)
    showToast(`„${a.original_filename}“ gelöscht`)
    await load()
  } catch (e) {
    showToast(apiFehler(e, 'Löschen fehlgeschlagen'), false)
  } finally {
    deleting.value = null
  }
}

// ── Darstellung ──────────────────────────────────────────────────────────────

/** Server liefert naive UTC-Zeitstempel – ohne „Z" würde der Browser lokal deuten. */
function formatDate(ts: string | null) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-2">
      <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Dateien</h3>
      <span v-if="items.length" class="text-xs text-gray-400">({{ items.length }})</span>
      <button
        v-if="canEdit"
        type="button"
        class="ml-auto btn-secondary !py-1.5 !text-sm"
        :disabled="uploading"
        @click="pickFile(null)"
      >{{ uploading ? 'Wird hochgeladen…' : 'Datei hochladen' }}</button>
    </div>

    <!-- Ein einziges Eingabefeld für alle Upload-Wege (neu + neue Version). -->
    <input ref="fileInput" type="file" class="hidden" @change="onFileChosen" />

    <div
      v-if="fehler"
      class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
             px-4 py-3 text-sm text-red-700 dark:text-red-200"
    >{{ fehler }}</div>

    <div v-else-if="loading && !items.length" class="flex items-center justify-center py-8">
      <div class="w-6 h-6 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <p v-else-if="!items.length" class="text-sm text-gray-400 italic px-1">
      Noch keine Dateien hochgeladen
    </p>

    <ul v-else class="divide-y divide-gray-100 dark:divide-white/[0.06] rounded-xl
                      border border-gray-200 dark:border-white/10 overflow-hidden">
      <li
        v-for="a in items" :key="a.id"
        class="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-50 dark:hover:bg-white/[0.03] transition"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <a
              :href="downloadUrl(a.id)"
              class="truncate text-sm text-[#3EAAB8] hover:underline"
              :title="a.original_filename"
            >{{ a.original_filename }}</a>
            <span
              v-if="a.version > 1"
              class="text-[11px] font-medium px-1.5 py-0.5 rounded-full whitespace-nowrap
                     bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400"
            >v{{ a.version }}</span>
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400 truncate">
            {{ a.size_human }} · {{ a.uploaded_by_name || 'Unbekannt' }} ·
            {{ formatDate(a.uploaded_at) }}
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <a
            :href="downloadUrl(a.id)"
            class="text-[#3EAAB8] hover:underline text-sm"
            title="Herunterladen"
          >⬇</a>
          <button
            v-if="canEdit"
            type="button"
            class="text-xs text-gray-500 dark:text-gray-400 hover:underline disabled:opacity-40"
            :disabled="uploading"
            title="Neue Version dieser Datei hochladen"
            @click="pickFile(a.family_id)"
          >Neue Version</button>
          <button
            v-if="canEdit"
            type="button"
            class="text-red-500 hover:text-red-600 disabled:opacity-40"
            :disabled="deleting === a.id"
            title="Löschen"
            @click="remove(a)"
          >🗑</button>
        </div>
      </li>
    </ul>
  </div>
</template>
