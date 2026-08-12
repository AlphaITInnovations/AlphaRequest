<script setup lang="ts">
/**
 * Verlauf eines Prozess-Auftrags samt Nachtrag-Eingabe.
 *
 * Der Server liefert den Verlauf schon redigiert (nicht sichtbare Felder und
 * fremde interne Nachträge fehlen) – hier wird NICHT nachgefiltert. Was ankommt,
 * darf gezeigt werden.
 *
 * `canComment` und `canBeInternal` steuern nur die Oberfläche; verbindlich prüft
 * der Server (Leserecht bzw. „bearbeitende Seite" für interne Nachträge).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { addComment, listEvents, type ProcessEvent } from '@/api/processEvents'
import { absoluteTime, eventSummary, eventTone, relativeTime } from '@/lib/processEventLabels'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Feld-Schlüssel → Beschriftung (aus der gepinnten Definition). */
  fieldLabels?: Record<string, string>
  phaseLabels?: Record<string, string>
  groupName?: (id: string) => string
  canComment?: boolean
  canBeInternal?: boolean
}>(), { canComment: true, canBeInternal: false })

const { showToast } = useToast()

const items = ref<ProcessEvent[]>([])
const loading = ref(false)
const fehler = ref<string | null>(null)
const text = ref('')
const internal = ref(false)
const sending = ref(false)
/** Nur den Anfang zeigen, bis „alles anzeigen" geklickt wird. */
const alleZeigen = ref(false)
const KURZ = 6

const MAX_LEN = 5000        // muss zum Server passen (MAX_COMMENT_LEN)

const ctx = computed(() => ({
  fieldLabels: props.fieldLabels,
  phaseLabels: props.phaseLabels,
  groupName: props.groupName,
}))

/** Neueste zuerst – der Server liefert chronologisch aufsteigend. */
const sortiert = computed(() => [...items.value].reverse())
const sichtbar = computed(() =>
  alleZeigen.value ? sortiert.value : sortiert.value.slice(0, KURZ))

const TONE_DOT: Record<string, string> = {
  neutral: 'bg-gray-300 dark:bg-white/25',
  progress: 'bg-[#3EAAB8]',
  warn: 'bg-amber-400',
  danger: 'bg-red-500',
  comment: 'bg-violet-400',
}

/** Läufe zählen: nach einer Wiederaufnahme beginnt ein neuer Durchlauf. */
const mehrereEpochen = computed(() => new Set(items.value.map((e) => e.epoch)).size > 1)

async function load() {
  loading.value = true
  fehler.value = null
  try {
    const res = await listEvents(props.ticketId, { limit: 500 })
    items.value = res.items
  } catch (e) {
    fehler.value = errorMessage(e, 'Verlauf konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

async function send() {
  const body = text.value.trim()
  if (!body) return
  sending.value = true
  try {
    const ev = await addComment(props.ticketId, body, internal.value)
    items.value = [...items.value, ev]
    text.value = ''
    internal.value = false
    showToast('Nachtrag gespeichert')
  } catch (e) {
    showToast(errorMessage(e, 'Nachtrag konnte nicht gespeichert werden'), false)
  } finally {
    sending.value = false
  }
}

/** Von außen nach einer Aktion (Speichern/Weiterschalten) neu laden. */
defineExpose({ reload: load })

onMounted(load)
watch(() => props.ticketId, load)
</script>

<template>
  <div class="card-section">
    <div class="flex items-center justify-between gap-2 mb-3">
      <h3 class="section-title mb-0">Verlauf</h3>
      <button @click="load" :disabled="loading"
              class="text-xs text-gray-400 hover:text-[#3EAAB8] disabled:opacity-40">
        Aktualisieren
      </button>
    </div>

    <!-- Nachtrag schreiben -->
    <div v-if="canComment" class="mb-4">
      <textarea v-model="text" rows="2" :maxlength="MAX_LEN"
                placeholder="Nachtrag schreiben – z. B. eine Rückfrage oder eine Ergänzung …"
                class="afi w-full resize-y" />
      <div class="flex items-center justify-between gap-3 mt-2 flex-wrap">
        <label v-if="canBeInternal"
               class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
          <input type="checkbox" v-model="internal"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]" />
          Nur intern
          <span class="text-gray-400">(sieht die antragstellende Person nicht)</span>
        </label>
        <span v-else />
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-gray-400">{{ text.length }}/{{ MAX_LEN }}</span>
          <button @click="send" :disabled="sending || !text.trim()"
                  class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8]
                         hover:bg-[#369aa7] disabled:opacity-40 transition">
            Nachtrag speichern
          </button>
        </div>
      </div>
    </div>

    <div v-if="fehler" class="text-sm text-red-600 mb-2">{{ fehler }}</div>
    <div v-else-if="loading && !items.length" class="text-sm text-gray-400">Wird geladen …</div>
    <p v-else-if="!items.length" class="text-sm text-gray-400 italic">
      Noch keine Einträge.
    </p>

    <ol v-else class="relative space-y-3 pl-5">
      <!-- Zeitachse -->
      <span class="absolute left-[5px] top-1 bottom-1 w-px bg-gray-200 dark:bg-white/10" />
      <li v-for="ev in sichtbar" :key="ev.id" class="relative">
        <span class="absolute -left-5 top-1.5 w-2.5 h-2.5 rounded-full ring-2 ring-white
                     dark:ring-[#1b2430]"
              :class="TONE_DOT[eventTone(ev)]" />
        <div class="flex items-baseline gap-2 flex-wrap">
          <span class="text-sm text-gray-800 dark:text-gray-100">
            {{ eventSummary(ev, ctx) }}
          </span>
          <span v-if="ev.internal"
                class="px-1.5 py-0.5 rounded text-[10px] bg-violet-100 text-violet-700
                       dark:bg-violet-900/30 dark:text-violet-300">intern</span>
          <span v-if="mehrereEpochen"
                class="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-500
                       dark:bg-white/10 dark:text-gray-400">Durchlauf {{ ev.epoch + 1 }}</span>
        </div>
        <div class="text-[11px] text-gray-400 flex items-center gap-1.5 flex-wrap">
          <span>{{ ev.actor_type === 'system' ? 'System' : (ev.actor_name || '—') }}</span>
          <span>·</span>
          <span :title="absoluteTime(ev.created_at)">{{ relativeTime(ev.created_at) }}</span>
        </div>
        <!-- Freitext (Nachtrag, Abteilungs-Notiz, Grund einer Wiederaufnahme) -->
        <p v-if="ev.body"
           class="mt-1 text-sm whitespace-pre-wrap rounded-lg px-3 py-2
                  bg-gray-50 dark:bg-white/[0.04] text-gray-700 dark:text-gray-200">{{ ev.body }}</p>
      </li>
    </ol>

    <button v-if="sortiert.length > KURZ" @click="alleZeigen = !alleZeigen"
            class="mt-3 text-xs text-[#3EAAB8] hover:underline">
      {{ alleZeigen ? 'Weniger anzeigen' : `Alle ${sortiert.length} Einträge anzeigen` }}
    </button>
  </div>
</template>
