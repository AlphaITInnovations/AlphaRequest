<script setup lang="ts">
/**
 * Nachträge zu einem bereits ABGESCHLOSSENEN Auftrag.
 *
 * Zeigt die vorhandenen Nachträge (neueste zuerst) direkt in der Auftragsansicht
 * und erlaubt einer beteiligten Person, einen weiteren hinzuzufügen. Beim Absenden
 * werden ALLE beteiligten Fachabteilungen per E-Mail informiert – der Auftrag
 * bleibt abgeschlossen (nichts am Status ändert sich). Zugriff/Zustand prüft das
 * Backend; die Nachträge tragen nur Freitext (keine Feld-Metadaten).
 */
import { ref, computed, onMounted, watch } from 'vue'
import { addAddendum, listAddenda, type ProcessEvent } from '@/api/processEvents'
import { absoluteTime, relativeTime } from '@/lib/processEventLabels'
import { errorMessage } from '@/lib/processErrors'

const props = defineProps<{ ticketId: number }>()
/** Dem Elternteil erlauben, den (Admin-)Verlauf nachzuladen. */
const emit = defineEmits<{ (e: 'sent'): void }>()

const MAX = 5000
const items = ref<ProcessEvent[]>([])
const offen = ref(false)
const text = ref('')
const busy = ref(false)
const fehler = ref<string | null>(null)

const zuLang = computed(() => text.value.length > MAX)
const absendbar = computed(() => !!text.value.trim() && !zuLang.value && !busy.value)

async function load() {
  try {
    items.value = await listAddenda(props.ticketId)
  } catch {
    // Still: die Liste ist Beiwerk – ein Ladefehler soll die Seite nicht stören.
    items.value = []
  }
}

function oeffnen() {
  offen.value = true
  fehler.value = null
}

function abbrechen() {
  offen.value = false
  text.value = ''
  fehler.value = null
}

async function senden() {
  if (!absendbar.value) return
  busy.value = true
  fehler.value = null
  try {
    await addAddendum(props.ticketId, text.value.trim())
    offen.value = false
    text.value = ''
    await load()
    emit('sent')
  } catch (e) {
    fehler.value = errorMessage(e, 'Nachtrag konnte nicht gesendet werden')
  } finally {
    busy.value = false
  }
}

onMounted(load)
watch(() => props.ticketId, load)
</script>

<template>
  <div class="card-section">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="section-title mb-1">Nachträge</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Ist nach dem Abschluss noch etwas hinzugekommen? Hinterlasse einen Nachtrag –
          alle beteiligten Fachabteilungen werden per E-Mail informiert. Der Auftrag
          bleibt abgeschlossen.
        </p>
      </div>
      <button v-if="!offen" @click="oeffnen" class="btn-secondary flex-shrink-0 text-sm">
        Nachtrag hinzufügen
      </button>
    </div>

    <!-- Vorhandene Nachträge (neueste zuerst) -->
    <ul v-if="items.length" class="mt-4 space-y-2">
      <li v-for="ev in items" :key="ev.id"
          class="rounded-xl border border-gray-100 dark:border-white/[0.06]
                 bg-gray-50 dark:bg-white/[0.03] px-3.5 py-2.5">
        <div class="flex items-center gap-1.5 text-[11px] text-gray-400">
          <span class="font-medium text-gray-500 dark:text-gray-300">{{ ev.actor_name || '—' }}</span>
          <span>·</span>
          <span :title="absoluteTime(ev.created_at)">{{ relativeTime(ev.created_at) }}</span>
        </div>
        <p class="mt-1 text-sm whitespace-pre-wrap text-gray-700 dark:text-gray-200">{{ ev.body }}</p>
      </li>
    </ul>
    <p v-else class="mt-3 text-sm text-gray-400 italic">Noch keine Nachträge.</p>

    <!-- Eingabe -->
    <div v-if="offen" class="mt-3 space-y-2">
      <textarea v-model="text" rows="5" :maxlength="MAX" autofocus
                placeholder="Was ist nachzutragen? Dieser Text geht an alle beteiligten Fachabteilungen."
                class="w-full rounded-xl border border-gray-200 dark:border-white/10
                       bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                       placeholder-gray-400 px-3.5 py-2.5 text-sm resize-y
                       focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
      <div class="flex items-center justify-between gap-3">
        <span class="text-[11px]" :class="zuLang ? 'text-red-500' : 'text-gray-400'">
          {{ text.length }} / {{ MAX }}
        </span>
        <div class="flex items-center gap-2">
          <button @click="abbrechen" :disabled="busy" class="btn-secondary text-sm">Abbrechen</button>
          <button @click="senden" :disabled="!absendbar"
                  class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                         disabled:opacity-40 transition">
            {{ busy ? 'Wird gesendet…' : 'Senden' }}
          </button>
        </div>
      </div>
      <p v-if="fehler" class="text-sm text-red-600 dark:text-red-300">{{ fehler }}</p>
    </div>
  </div>
</template>
