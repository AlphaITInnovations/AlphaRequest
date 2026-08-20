<script setup lang="ts">
/**
 * Beobachter:innen eines Prozess-Auftrags.
 *
 * Beobachten heißt AUSSCHLIESSLICH: mitlesen dürfen, ohne zuständig zu sein.
 * Es gehen KEINE Mails an Beobachter:innen – der Auftrag erscheint in der
 * Übersicht und zeigt dort den aktuellen Bearbeitungsstand.
 *
 * Sich selbst darf jede Person mit Leserecht ein-/austragen. FREMDE einzutragen
 * ist eine Rechte-Vergabe und daher der zuständigen Stelle vorbehalten
 * (`canManage` blendet die Auswahl aus; verbindlich prüft der Server).
 *
 * `embedded` ist die Panel-Optik: ohne eigene Karte und mit kleiner Überschrift,
 * damit die Liste als Abschnitt in `ProcessDetailsPanel.vue` sitzt. Sonst bliebe
 * eine Karte in der Karte – und es gäbe zwei Beobachter-Komponenten.
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  addWatcher, listWatchers, removeWatcher, type ProcessWatcher,
} from '@/api/processEvents'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'
import UserSelect from '@/components/UserSelect.vue'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Angemeldete Person – darf sich selbst ein-/austragen (ohne `canManage`). */
  currentUserId?: string | null
  /** Darf FREMDE Personen ein-/austragen? */
  canManage?: boolean
  /** Auswahlliste für das Eintragen (Suche im Dropdown). */
  users?: { id: string; displayName: string }[]
  /** Panel-Optik: ohne eigene Karte, kleine Überschrift (siehe Docstring). */
  embedded?: boolean
}>(), { currentUserId: null, canManage: false, users: () => [], embedded: false })

const emit = defineEmits<{ changed: [watchers: ProcessWatcher[]] }>()

const { showToast } = useToast()

const items = ref<ProcessWatcher[]>([])
const loading = ref(false)
const busy = ref(false)
const fehler = ref<string | null>(null)
/** Gebunden an UserSelect – beim Auswählen wird sofort eingetragen. */
const auswahl = ref<{ id: string; name: string } | null>(null)

/**
 * Wer im Dropdown gefunden werden kann: mit Verwaltungsrecht ALLE noch nicht
 * eingetragenen Personen; ohne Recht ausschließlich man selbst (jede Person
 * darf sich selbst eintragen – durch Suche nach dem eigenen Namen). Bereits
 * Eingetragene fallen raus.
 */
const auswaehlbar = computed(() => {
  const drin = new Set(items.value.map((w) => w.id))
  const offen = props.users.filter((u) => !drin.has(u.id))
  if (props.canManage) return offen
  return props.currentUserId ? offen.filter((u) => u.id === props.currentUserId) : []
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
    auswahl.value = null
  } catch (e) {
    showToast(errorMessage(e, 'Beobachtung konnte nicht geändert werden'), false)
  } finally {
    busy.value = false
  }
}

/** UserSelect meldet eine Auswahl → sofort eintragen (kein extra Knopf mehr). */
function onAuswahl(sel: { id: string; name: string } | null) {
  auswahl.value = sel
  if (sel && !busy.value) umstellen(true, sel.id)
}

onMounted(load)
watch(() => props.ticketId, load)
</script>

<template>
  <div :class="embedded ? '' : 'card-section'">
    <div class="mb-2">
      <h3 :class="embedded
            ? 'text-xs font-semibold text-gray-400 uppercase tracking-wider'
            : 'section-title mb-0'">Beobachter:innen</h3>
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

    <!-- Eintragen per Suche: beim Auswählen wird sofort hinzugefügt (kein extra
         Knopf). Ohne Verwaltungsrecht findet man ausschließlich sich selbst. -->
    <div v-if="auswaehlbar.length" class="mt-3">
      <UserSelect :model-value="auswahl" label=""
                  :placeholder="canManage ? 'Person suchen und hinzufügen…' : 'Nach eigenem Namen suchen…'"
                  :show-users="true" :show-groups="false"
                  :users="auswaehlbar" :disabled="busy"
                  @update:model-value="onAuswahl" />
    </div>

    <!-- Datenschutz-Hinweis: wer beobachtet, liest ALLES mit. Steht nur dort, wo
         fremde Personen eingetragen werden können – dort ist es eine Entscheidung. -->
    <p v-if="canManage"
       class="mt-2 flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400/90">
      <svg class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24"
           stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round"
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span>Beobachter:innen sehen <strong>alle sichtbaren Angaben</strong> des Auftrags.</span>
    </p>
  </div>
</template>

