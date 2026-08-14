<script setup lang="ts">
/**
 * Verlauf eines Prozess-Auftrags.
 *
 * Der Server liefert den Verlauf schon redigiert (nicht sichtbare Felder und
 * fremde interne Nachträge fehlen) – hier wird NICHT nach Rechten gefiltert. Was
 * ankommt, darf gezeigt werden.
 *
 * NACHTRÄGE RUHEN – NUR IN DER OBERFLÄCHE
 * ---------------------------------------
 * Die Nachtrags-Eingabe und die Nachtrags-EINTRÄGE (`action='comment'`) werden
 * derzeit nicht gezeigt. Das ist eine reine Anzeige-Entscheidung: Tabelle,
 * Endpunkte (`api/processEvents.addComment`) und der Verlauf selbst bleiben
 * unverändert, ältere Nachträge stehen weiter in der Datenbank. Zurückholen
 * heißt: den Filter unten entfernen und die Eingabe wieder einsetzen (die
 * Rechte-Angaben `canComment`/`canBeInternal` sind dafür absichtlich noch da).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { listEvents, type ProcessEvent } from '@/api/processEvents'
import { absoluteTime, eventSummary, eventTone, relativeTime } from '@/lib/processEventLabels'
import { errorMessage } from '@/lib/processErrors'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Feld-Schlüssel → Beschriftung (aus der gepinnten Definition). */
  fieldLabels?: Record<string, string>
  phaseLabels?: Record<string, string>
  groupName?: (id: string) => string
  /** Ruht mit der Nachtrags-Eingabe (siehe Docstring) – bleibt für die Rückkehr. */
  canComment?: boolean
  canBeInternal?: boolean
}>(), { canComment: true, canBeInternal: false })

const items = ref<ProcessEvent[]>([])
const loading = ref(false)
const fehler = ref<string | null>(null)
/** Nur den Anfang zeigen, bis „alles anzeigen" geklickt wird. */
const alleZeigen = ref(false)
const KURZ = 6

const ctx = computed(() => ({
  fieldLabels: props.fieldLabels,
  phaseLabels: props.phaseLabels,
  groupName: props.groupName,
}))

/**
 * Neueste zuerst – der Server liefert chronologisch aufsteigend.
 *
 * Nachträge (`action='comment'`) bleiben aus der ANZEIGE: nur die Oberfläche
 * ruht, geladen und gespeichert wird weiter alles (siehe Docstring). Gefiltert
 * wird erst hier und nicht beim Laden, damit `mehrereEpochen` und ein späteres
 * Wiedereinschalten den vollen Verlauf sehen.
 */
const sortiert = computed(() =>
  [...items.value].reverse().filter((e) => e.action !== 'comment'))
const sichtbar = computed(() =>
  alleZeigen.value ? sortiert.value : sortiert.value.slice(0, KURZ))

const TONE_DOT: Record<string, string> = {
  neutral: 'bg-gray-300 dark:bg-white/25',
  progress: 'bg-[#3EAAB8]',
  warn: 'bg-amber-400',
  danger: 'bg-red-500',
  // Nachträge sind derzeit ausgeblendet; der Ton bleibt für ihre Rückkehr stehen.
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

    <!-- Die Nachtrags-Eingabe fehlt ABSICHTLICH: die Nachtrags-Oberfläche ruht
         (siehe Docstring). Endpunkt und Datenbank sind unverändert. -->

    <div v-if="fehler" class="text-sm text-red-600 mb-2">{{ fehler }}</div>
    <div v-else-if="loading && !items.length" class="text-sm text-gray-400">Wird geladen …</div>
    <p v-else-if="!sortiert.length" class="text-sm text-gray-400 italic">
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
        <!-- Freitext eines Ereignisses: Abteilungs-Notiz, Ablehnungs- oder
             Wiederaufnahme-Grund. Nachträge sind hier nicht dabei (ausgefiltert). -->
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
