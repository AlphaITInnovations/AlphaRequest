<script setup lang="ts">
/**
 * Anzeigereihenfolge der Prozesse im Katalog „Neues Prozess-Ticket"
 * (/prozess-auftraege/neu). Der Admin legt EINE globale Reihenfolge fest; sie
 * gilt für alle. WELCHE Prozesse jemand dort tatsächlich sieht, entscheidet
 * weiterhin das Anlege-Recht (createPermissions / may_create) – die Reihenfolge
 * ändert daran nichts, sortiert nur.
 *
 * Bewusst per Hoch/Runter (kein Drag&Drop): robust, tastaturbedienbar und ohne
 * zusätzliche Abhängigkeit. Das Basis-Ticket fehlt hier – es hat einen eigenen
 * Einstieg und steht nicht im Prozess-Katalog.
 */
import { ref, computed, onMounted } from 'vue'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { getProcessOrder, saveProcessOrder, type ProcessOrderItem } from '@/api/processes'
import { errorMessage } from '@/lib/processErrors'

const { showToast } = useToast()

const items = ref<ProcessOrderItem[]>([])
const snapshot = ref('')
const loading = ref(true)
const loadError = ref<string | null>(null)

const keys = (list: ProcessOrderItem[]) => list.map((p) => p.key).join('\n')

async function load() {
  loading.value = true
  loadError.value = null
  try {
    items.value = await getProcessOrder()
    snapshot.value = keys(items.value)
  } catch (e) {
    loadError.value = errorMessage(e, 'Reihenfolge konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

function move(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= items.value.length) return
  const list = items.value
  ;[list[i], list[j]] = [list[j], list[i]]
}

async function saveOrder() {
  setSaving(true)
  try {
    items.value = await saveProcessOrder(items.value.map((p) => p.key))
    snapshot.value = keys(items.value)
    showToast('Reihenfolge gespeichert', true)
  } catch (e) {
    showToast(errorMessage(e, 'Speichern fehlgeschlagen'), false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => keys(items.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save: saveOrder, reset: () => load() })

onMounted(load)
</script>

<template>
  <section>
    <h2 class="section-title mb-1">Reihenfolge Prozesse</h2>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Legt die Reihenfolge der Kacheln im Tab <span class="font-medium">„Neues Prozess-Ticket"</span> fest.
      Das ist nur eine Sortierung – <span class="font-medium">welche</span> Prozesse jemand dort sieht,
      hängt weiterhin am Anlege-Recht des Prozesses. Das Basis-Ticket erscheint hier nicht (eigener Einstieg).
    </div>

    <div v-if="loadError"
         class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                px-4 py-3 text-sm text-red-800 dark:text-red-200 mb-4">
      {{ loadError }}
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <p v-else-if="!items.length" class="text-sm text-gray-400 italic py-8">
      Es ist noch kein Prozess veröffentlicht.
    </p>

    <ul v-else class="space-y-2">
      <li v-for="(p, i) in items" :key="p.key"
          class="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-white/10
                 bg-white dark:bg-[#212B3A] px-4 py-3">
        <span class="w-6 text-right text-sm tabular-nums text-gray-400">{{ i + 1 }}</span>
        <span class="text-xl leading-none">{{ p.icon || '📄' }}</span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">{{ p.name }}</p>
          <p class="text-[11px] font-mono text-gray-400 truncate">{{ p.key }}</p>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button type="button" @click="move(i, -1)" :disabled="i === 0"
                  class="w-8 h-8 rounded-lg border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-30 transition"
                  title="Nach oben">↑</button>
          <button type="button" @click="move(i, 1)" :disabled="i === items.length - 1"
                  class="w-8 h-8 rounded-lg border border-gray-200 dark:border-white/10
                         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-30 transition"
                  title="Nach unten">↓</button>
        </div>
      </li>
    </ul>
  </section>
</template>
