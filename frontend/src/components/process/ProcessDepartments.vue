<script setup lang="ts">
/**
 * Fachabteilungen einer Fachabteilungs-Phase: Stand je Abteilung anzeigen und
 * abschließen. Eine beteiligte Fachabteilung MUSS ausführen – es gibt darum nur
 * die Aktion „Erledigt" (kein „nicht zuständig", kein „ablehnen").
 *
 * Ohne diese Oberfläche sind Aufträge, die in einer Fachabteilungs-Phase stehen,
 * NICHT abschließbar: `:advance` antwortet mit 409 DEPARTMENT_FORBIDDEN, solange
 * eine Pflicht-Abteilung offen ist.
 *
 * WER DEN KNOPF SIEHT
 * -------------------
 * Nur wer in der jeweiligen Abteilung Mitglied ist. Die Mitgliedschaft kennt das
 * Frontend NICHT selbst – der Server liefert sie in `ticket.abilities.
 * completable_departments` und die Detailansicht reicht sie als `myGroupIds`
 * herein. `null` heißt „unbekannt → alles anbieten" (Alt-/Fallback-Fall), der
 * Server bleibt aber verbindlich (process_access.may_complete_department).
 *
 * `focusDepartment` verengt zusätzlich auf GENAU die Abteilung, mit der die
 * Person den Auftrag aufgerufen hat (aus der Dashboard-URL, ?abteilung=…) –
 * nützlich, wenn jemand in mehreren Abteilungen ist.
 *
 * Eingehängt in `views/processes/ProcessTicketDetailView.vue`; der aktualisierte
 * Auftrag kommt per `updated`-Ereignis zurück (Fortschritt und Zuständigkeit im
 * Kopf ändern sich dadurch mit).
 */
import { computed, ref, watch } from 'vue'
import type { ProcessTicketOut } from '@/types/process'
import {
  departmentProgress, departmentStatusLabel, departmentTone, isDepartmentPending,
  isRequired, requiredLabel, type DepartmentState,
} from '@/lib/processDepartments'
import { errorCode, errorMessage } from '@/lib/processErrors'
import { absoluteTime, relativeTime } from '@/lib/processEventLabels'
import { completeDepartment } from '@/api/processTickets'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Live-Stand aus `ticket.responsibility.departments` (nur die aktuelle Phase). */
  departments: DepartmentState[]
  /** Gruppen-ID → Name; die Detailansicht hat die Namen über lib/processSources.ts. */
  groupName?: (id: string) => string
  /** Auftrag abgelehnt/archiviert? Dann gibt es nichts mehr zu quittieren. */
  terminal?: boolean
  /** Eigene Abteilungen (Server: abilities.completable_departments). `null` = unbekannt. */
  myGroupIds?: string[] | null
  /** Optional aus der URL: nur DIESE Abteilung bedienbar machen. */
  focusDepartment?: string | null
}>(), {
  groupName: undefined,
  terminal: false,
  myGroupIds: null,
  focusDepartment: null,
})

const emit = defineEmits<{ updated: [ticket: ProcessTicketOut] }>()

const { showToast } = useToast()

/** Gruppen-ID der laufenden Anfrage – sperrt währenddessen alle Knöpfe. */
const busy = ref<string | null>(null)
const fehler = ref<string | null>(null)

const fortschritt = computed(() => departmentProgress(props.departments))

const nameVon = (gid: string) => props.groupName?.(gid) || gid

/** Wird für DIESE Abteilung der „Erledigt"-Knopf angeboten? */
function bedienbar(d: DepartmentState): boolean {
  if (props.terminal || !isDepartmentPending(d)) return false
  // Optional auf die per URL aufgerufene Abteilung verengen.
  if (props.focusDepartment && d.group !== props.focusDepartment) return false
  // null = Mitgliedschaft unbekannt → anbieten, der Server entscheidet.
  return props.myGroupIds === null || props.myGroupIds.includes(d.group)
}

/** Es gibt offene Pflicht-Abteilungen, aber KEINE davon darf diese Person
 *  quittieren (weder Mitglied noch – bei Fokus – die passende). */
const nichtsFuerMich = computed(() =>
  !props.terminal
  && props.departments.some((d) => isDepartmentPending(d) && isRequired(d))
  && !props.departments.some(bedienbar))

/** Offene Abteilungen zuerst: dort steht die Arbeit an. */
const sortiert = computed(() => [...props.departments].sort((a, b) =>
  Number(isDepartmentPending(b)) - Number(isDepartmentPending(a))))

// Ticketwechsel: ein alter Fehler gehört nicht zum nächsten Auftrag.
watch(() => props.ticketId, () => { fehler.value = null })

/**
 * Fehler in Klartext. Der 403 (DEPARTMENT_FORBIDDEN) sollte mit der server-
 * seitigen Vorauswahl praktisch nicht mehr auftreten, wird aber sicherheitshalber
 * verständlich gezeigt statt als roher Fehler.
 */
function aktionsFehler(e: unknown, gid: string): string {
  const status = (e as { response?: { status?: number } })?.response?.status
  if (status === 403 && errorCode(e) === 'DEPARTMENT_FORBIDDEN') {
    return `Nur Mitglieder von „${nameVon(gid)}“ können hier abschließen.`
  }
  return errorMessage(e, 'Die Fachabteilung konnte nicht abgeschlossen werden')
}

function erledigt(gid: string) {
  busy.value = gid
  fehler.value = null
  completeDepartment(props.ticketId, gid, null)
    .then((ticket) => {
      showToast(`${nameVon(gid)}: erledigt`)
      emit('updated', ticket)
    })
    .catch((e) => { fehler.value = aktionsFehler(e, gid) })
    .finally(() => { busy.value = null })
}

const TONE_CLASS: Record<string, string> = {
  open: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  done: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  skipped: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  unknown: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
}
const toneClass = (d: DepartmentState) => TONE_CLASS[departmentTone(d.status)]
</script>

<template>
  <div class="card-section">
    <div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
      <h3 class="section-title mb-0">Fachabteilungen</h3>
      <span class="text-xs px-2.5 py-1 rounded-full"
            :class="fortschritt.ready
              ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
              : 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400'">
        {{ fortschritt.text }}
      </span>
    </div>

    <p v-if="!departments.length" class="text-sm text-gray-400 italic">
      An dieser Phase ist keine Fachabteilung beteiligt.
    </p>

    <template v-else>
      <!-- Worauf gewartet wird: das ist die Frage vor „warum geht es nicht weiter?" -->
      <p v-if="fortschritt.openRequired" class="text-xs text-gray-500 dark:text-gray-400 mb-3">
        Der Phasenabschluss wartet noch auf
        {{ fortschritt.openRequired }} Pflicht-Abteilung{{ fortschritt.openRequired === 1 ? '' : 'en' }}.
      </p>
      <p v-else-if="!terminal" class="text-xs text-green-700 dark:text-green-300 mb-3">
        Alle Pflicht-Abteilungen sind fertig – die Phase kann abgeschlossen werden.
      </p>

      <div v-if="fehler"
           class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                  px-4 py-3 text-sm text-red-700 dark:text-red-200 mb-3">
        {{ fehler }}
      </div>

      <ul class="divide-y divide-gray-100 dark:divide-white/[0.06] rounded-xl
                 border border-gray-200 dark:border-white/10 overflow-hidden">
        <li v-for="d in sortiert" :key="d.group"
            class="px-3 py-2.5">
          <div class="flex items-start gap-3 flex-wrap">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm text-gray-800 dark:text-gray-100 truncate"
                      :title="d.group">{{ nameVon(d.group) }}</span>
                <span class="text-[11px] font-medium px-1.5 py-0.5 rounded-full whitespace-nowrap"
                      :class="isRequired(d)
                        ? 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400'
                        : 'bg-transparent border border-gray-200 dark:border-white/15 text-gray-400'">
                  {{ requiredLabel(d.required) }}
                </span>
                <span class="text-[11px] font-medium px-1.5 py-0.5 rounded-full whitespace-nowrap"
                      :class="toneClass(d)">{{ departmentStatusLabel(d.status) }}</span>
              </div>
              <div v-if="!isDepartmentPending(d)" class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {{ d.by_name || d.by || 'Unbekannt' }}
                <span v-if="d.at" :title="absoluteTime(d.at)">· {{ relativeTime(d.at) }}</span>
              </div>
              <p v-if="d.note"
                 class="text-xs text-gray-600 dark:text-gray-300 mt-1 whitespace-pre-wrap
                        border-l-2 border-gray-200 dark:border-white/15 pl-2">{{ d.note }}</p>
            </div>

            <div v-if="bedienbar(d)" class="shrink-0">
              <button type="button" :disabled="!!busy"
                      class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                             disabled:opacity-40 transition"
                      @click="erledigt(d.group)">
                {{ busy === d.group ? 'Wird abgeschlossen …' : 'Erledigt' }}
              </button>
            </div>
          </div>
        </li>
      </ul>

      <p v-if="nichtsFuerMich" class="text-[11px] text-gray-400 mt-2">
        Diese Phase wartet auf andere Fachabteilungen – für deine Abteilung ist hier
        gerade nichts zu tun.
      </p>
    </template>
  </div>
</template>
