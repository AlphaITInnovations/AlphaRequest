<script setup lang="ts">
/**
 * Beobachter:innen eines Prozess-Auftrags.
 *
 * Beobachten heißt: mitlesen dürfen, ohne zuständig zu sein – und über
 * Phasenwechsel und Nachträge benachrichtigt werden.
 *
 * Sich selbst darf jede Person mit Leserecht ein-/austragen. FREMDE einzutragen
 * ist eine Rechte-Vergabe und daher der zuständigen Stelle vorbehalten
 * (`canManage` blendet die Auswahl aus; verbindlich prüft der Server).
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  addWatcher, listWatchers, removeWatcher, type ProcessWatcher,
} from '@/api/processEvents'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Angemeldete Person – für „ich beobachte" und das Entfernen ohne Rückfrage. */
  currentUserId?: string | null
  /** Darf fremde Personen ein-/austragen? */
  canManage?: boolean
  /** Auswahlliste für das Eintragen fremder Personen. */
  users?: { id: string; displayName: string }[]
}>(), { currentUserId: null, canManage: false, users: () => [] })

const emit = defineEmits<{ changed: [watchers: ProcessWatcher[]] }>()

const { showToast } = useToast()

const items = ref<ProcessWatcher[]>([])
const loading = ref(false)
const busy = ref(false)
const fehler = ref<string | null>(null)
const auswahl = ref('')

const beobachteIch = computed(() =>
  !!props.currentUserId && items.value.some((w) => w.id === props.currentUserId))

/** Nur Personen anbieten, die noch nicht beobachten. */
const offeneUsers = computed(() => {
  const drin = new Set(items.value.map((w) => w.id))
  return props.users.filter((u) => !drin.has(u.id))
})

const nameVon = (w: ProcessWatcher) =>
  w.name || props.users.find((u) => u.id === w.id)?.displayName || w.id

async function load() {
  loading.value = true
  fehler.value = null
  try {
    items.value = await listWatchers(props.ticketId)
  } catch (e) {
    fehler.value = errorMessage(e, 'Beobachter:innen konnten nicht geladen werden')
  } finally {
    loading.value = false
  }
}

async function umstellen(hinzu: boolean, userId?: string) {
  busy.value = true
  try {
    items.value = hinzu
      ? await addWatcher(props.ticketId, userId ?? null)
      : await removeWatcher(props.ticketId, userId || props.currentUserId || '')
    emit('changed', items.value)
    auswahl.value = ''
  } catch (e) {
    showToast(errorMessage(e, 'Beobachtung konnte nicht geändert werden'), false)
  } finally {
    busy.value = false
  }
}

onMounted(load)
watch(() => props.ticketId, load)
</script>

<template>
  <div class="card-section">
    <div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
      <h3 class="section-title mb-0">Beobachter:innen</h3>
      <button v-if="currentUserId" @click="umstellen(!beobachteIch)" :disabled="busy"
              class="text-xs px-2.5 py-1 rounded-lg border transition disabled:opacity-40"
              :class="beobachteIch
                ? 'border-[#3EAAB8] text-[#3EAAB8] hover:bg-[#3EAAB8]/10'
                : 'border-gray-300 dark:border-white/20 text-gray-500 hover:text-[#3EAAB8]'">
        {{ beobachteIch ? '✓ Ich beobachte' : 'Beobachten' }}
      </button>
    </div>

    <div v-if="fehler" class="text-sm text-red-600">{{ fehler }}</div>
    <p v-else-if="loading && !items.length" class="text-sm text-gray-400">Wird geladen …</p>
    <p v-else-if="!items.length" class="text-sm text-gray-400 italic">
      Niemand beobachtet diesen Auftrag.
    </p>

    <ul v-else class="flex flex-wrap gap-2">
      <li v-for="w in items" :key="w.id"
          class="flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full text-xs
                 bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200">
        <span>{{ nameVon(w) }}</span>
        <button v-if="canManage || w.id === currentUserId"
                @click="umstellen(false, w.id)" :disabled="busy"
                class="text-gray-400 hover:text-red-500 disabled:opacity-40"
                :aria-label="`${nameVon(w)} entfernen`">✕</button>
      </li>
    </ul>

    <!-- Fremde eintragen: nur die zuständige Stelle -->
    <div v-if="canManage && offeneUsers.length" class="flex items-center gap-2 mt-3">
      <select v-model="auswahl" class="afi flex-1 text-sm">
        <option value="">– Person hinzufügen –</option>
        <option v-for="u in offeneUsers" :key="u.id" :value="u.id">{{ u.displayName }}</option>
      </select>
      <button @click="umstellen(true, auswahl)" :disabled="busy || !auswahl"
              class="btn-secondary text-xs py-1.5">Hinzufügen</button>
    </div>
  </div>
</template>
