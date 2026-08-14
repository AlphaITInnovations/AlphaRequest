<script setup lang="ts">
/**
 * Details-Panel eines Prozess-Auftrags – die linke Spalte der Detailansicht.
 *
 * Reihenfolge wie in der früheren `components/TicketDetails.vue`:
 * Phasen-Fortschritt, Meta-Angaben, ZUSTÄNDIGE Stelle, Beobachter:innen.
 *
 * NICHT enthalten, bewusst:
 *  - PRIORITÄT: ist derzeit überall ausgeblendet, bis geklärt ist, wie sie
 *    sinnvoll genutzt wird. Das Feld bleibt in DB, API und Typen.
 *  - KOMMENTAR/NACHTRAG: die Nachtrags-Anzeige ruht (siehe ProcessTimeline.vue);
 *    der Verlauf bleibt sichtbar.
 *
 * NAMEN STATT IDs: `ticket.responsibility` kommt mit Gruppen- und Personen-IDs.
 * Die Namen reicht die Detailansicht als Funktionen herein (sie hat sie über
 * lib/processSources.ts) – dieses Panel lädt nichts nach.
 *
 * WEITERREICHEN: kommt die Zuständigkeit aus einem FELD des Auftrags
 * (kind='assignable'/'group_from_field') und ist dieses Feld in der aktuellen
 * Phase editierbar, lässt sich die Stelle hier direkt umstellen. Das ist der
 * Basis-Auftrag: Vorgänge zwischen Fachabteilungen hin- und herschieben, ohne
 * im Formular nach dem richtigen Feld zu suchen. Gespeichert wird über den
 * normalen PATCH-Weg der Detailansicht (`handover`-Ereignis) – damit gelten
 * dieselben Prüfungen und derselbe Verlauf wie beim „Speichern".
 */
import { computed, ref, watch } from 'vue'
import type { ProcessTicketOut } from '@/types/process'
import type { PhaseStepInput } from '@/lib/processPhaseProgress'
import { departmentProgress } from '@/lib/processDepartments'
import { describeResponsibility, handoverTarget } from '@/lib/processResponsibility'
import { STATUS_LABEL } from '@/lib/processSchema'
import { absoluteTime, relativeTime } from '@/lib/processEventLabels'
import ProcessPhaseProgress from '@/components/process/ProcessPhaseProgress.vue'
import ProcessWatchers from '@/components/process/ProcessWatchers.vue'

const props = withDefaults(defineProps<{
  ticket: ProcessTicketOut
  /** Phasen der gepinnten Definition – von dort kommen die Phasen-Namen. */
  phases: readonly PhaseStepInput[]
  /** Gruppen-ID → Name. */
  groupName?: (id: string) => string
  /** Personen-ID → Anzeigename. */
  userName?: (id: string) => string
  /** Feld-Schlüssel → Beschriftung (für „steht im Feld …"). */
  fieldName?: (key: string) => string
  /** Auswahl für das Weiterreichen an eine Fachabteilung. */
  groups?: { id: string; name: string }[]
  /** Auswahl für das Weiterreichen an eine Person – und für Beobachter:innen. */
  users?: { id: string; displayName: string }[]
  /** `abilities.edit` – Voraussetzung für das Weiterreichen (siehe unten). */
  canEdit?: boolean
  /** Darf diese Person fremde Beobachter:innen ein-/austragen? */
  canManageWatchers?: boolean
  currentUserId?: string | null
  /** Läuft schon eine Aktion (Speichern/Weiterschalten)? Dann keine zweite. */
  busy?: boolean
}>(), {
  groupName: undefined,
  userName: undefined,
  fieldName: undefined,
  groups: () => [],
  users: () => [],
  canEdit: false,
  canManageWatchers: false,
  currentUserId: null,
  busy: false,
})

const emit = defineEmits<{
  /** Feld-Schlüssel + neue Stelle; gespeichert wird in der Detailansicht. */
  handover: [field: string, value: string]
}>()

const zustaendig = computed(() => describeResponsibility(props.ticket.responsibility, {
  groupName: props.groupName,
  userName: props.userName,
  fieldName: props.fieldName,
  ownerName: props.ticket.owner_name,
}))

/** Nur bei Fachabteilungs-Phasen: der Stand steht als Zahl hier, die Liste in
 *  der Karte „Fachabteilungen" (keine doppelte Namensliste). */
const abteilungen = computed(() => {
  const r = props.ticket.responsibility
  return r?.kind === 'departments' ? departmentProgress(r.departments) : null
})

const weitergabe = computed(() =>
  handoverTarget(props.ticket.responsibility, props.ticket.editable_fields, props.canEdit))

/** Auswahl im Weitergabe-Feld; startet auf der aktuell zuständigen Stelle. */
const ziel = ref('')
watch(weitergabe, (w) => { ziel.value = w?.current ?? '' }, { immediate: true })

const zielAuswahl = computed<{ id: string; label: string }[]>(() => {
  if (weitergabe.value?.pick === 'group') {
    return props.groups.map((g) => ({ id: g.id, label: g.name }))
  }
  if (weitergabe.value?.pick === 'user') {
    return props.users.map((u) => ({ id: u.id, label: u.displayName }))
  }
  return []
})

/**
 * Beschriftung folgt dem Zustand: ist noch niemand eingetragen, wird EINGETRAGEN;
 * steht schon eine Stelle drin, wird WEITERGEREICHT. „Weiterreichen" auf einem
 * leeren Feld hätte sonst nach einem Fehler ausgesehen.
 */
const weitergabeText = computed(() => {
  const w = weitergabe.value
  if (!w) return null
  const stelle = w.pick === 'group' ? 'Fachabteilung' : 'Person'
  return {
    label: w.current ? `An andere ${stelle} weiterreichen` : `Zuständige ${stelle} eintragen`,
    aktion: w.current ? 'Weiterreichen' : 'Eintragen',
    platzhalter: `– ${stelle} wählen –`,
  }
})

/** Umstellen nur, wenn sich wirklich etwas ändert (sonst ein PATCH ohne Wirkung). */
const kannWeitergeben = computed(() =>
  !!weitergabe.value && !!ziel.value && ziel.value !== weitergabe.value.current && !props.busy)

function weiterreichen() {
  if (!weitergabe.value || !kannWeitergeben.value) return
  emit('handover', weitergabe.value.field, ziel.value)
}

const status = computed(() =>
  STATUS_LABEL[props.ticket.status] || props.ticket.status)
</script>

<template>
  <div class="card-section text-sm divide-y divide-gray-100 dark:divide-white/[0.06]">

    <!-- Fortschritt: „Phase X von Y" samt Namen -->
    <div class="pb-5">
      <ProcessPhaseProgress :phases="phases"
                            :current-index="ticket.runtime?.current_index ?? 0"
                            :rejected="!!ticket.runtime?.rejected" />
    </div>

    <!-- Meta -->
    <div class="py-5 space-y-4">
      <h2 class="text-base font-semibold text-gray-900 dark:text-white">Details</h2>
      <div>
        <p class="meta-label">Status</p>
        <p class="meta-value">{{ status }}</p>
      </div>
      <div>
        <p class="meta-label">Antragsteller:in</p>
        <p class="meta-value">{{ ticket.owner_name || '—' }}</p>
      </div>
      <div v-if="ticket.created_at">
        <p class="meta-label">Angelegt</p>
        <p class="meta-value" :title="absoluteTime(ticket.created_at)">
          {{ relativeTime(ticket.created_at) }}
        </p>
      </div>
    </div>

    <!-- Zuständigkeit / nächster Bearbeiter -->
    <div class="py-5 space-y-2">
      <p class="meta-label">Zuständig / nächster Bearbeiter</p>

      <!-- Niemand zuständig: der Auftrag bliebe unbemerkt liegen -->
      <div v-if="zustaendig.missing"
           class="rounded-xl border border-amber-300 dark:border-amber-400/40
                  bg-amber-50 dark:bg-amber-900/20 px-3 py-2.5 space-y-1">
        <p class="font-semibold text-amber-800 dark:text-amber-200 flex items-center gap-1.5">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24"
               stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round"
                  d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          </svg>
          Niemand zuständig
        </p>
        <p class="text-xs text-amber-800/90 dark:text-amber-200/90">{{ zustaendig.missingHint }}</p>
      </div>

      <template v-else>
        <p class="meta-value break-words">{{ zustaendig.name }}</p>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ zustaendig.roleLabel }}</p>
        <p v-if="abteilungen" class="text-xs text-gray-500 dark:text-gray-400">
          {{ abteilungen.text }} · Stand je Abteilung siehe „Fachabteilungen"
        </p>
      </template>

      <!-- Weiterreichen: nur wenn die Stelle aus einem editierbaren Feld kommt
           UND diese Person den Auftrag bearbeiten darf (siehe handoverTarget). -->
      <div v-if="weitergabe && weitergabeText" class="pt-2 space-y-2">
        <label class="meta-label mb-0" :for="`weitergabe-${ticket.id}`">
          {{ weitergabeText.label }}
        </label>
        <select :id="`weitergabe-${ticket.id}`" v-model="ziel" class="afi w-full" :disabled="busy">
          <option value="" disabled>{{ weitergabeText.platzhalter }}</option>
          <option v-for="o in zielAuswahl" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select>
        <p v-if="!zielAuswahl.length" class="text-[11px] text-amber-600 dark:text-amber-400">
          Keine Auswahl verfügbar – die Namensliste konnte nicht geladen werden.
        </p>
        <button type="button" class="btn-secondary w-full !text-sm"
                :disabled="!kannWeitergeben" @click="weiterreichen">
          {{ weitergabeText.aktion }}
        </button>
        <p class="text-[11px] text-gray-400">
          Wird sofort gespeichert. Ab dann ist die gewählte Stelle zuständig – Feld
          „{{ fieldName?.(weitergabe.field) || weitergabe.field }}".
        </p>
      </div>
    </div>

    <!-- Beobachter:innen (chrome-los eingebettet) -->
    <div class="pt-5">
      <ProcessWatchers embedded :ticket-id="ticket.id" :current-user-id="currentUserId"
                       :can-manage="canManageWatchers" :users="users" />
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.meta-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1; }
.meta-value { @apply font-medium text-gray-900 dark:text-white; }
.afi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
