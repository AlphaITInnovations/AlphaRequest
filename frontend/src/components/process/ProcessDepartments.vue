<script setup lang="ts">
/**
 * Fachabteilungen einer Fachabteilungs-Phase: Stand je Abteilung anzeigen und
 * quittieren (erledigt / nicht zuständig / ablehnen).
 *
 * Ohne diese Oberfläche sind Aufträge, die in einer Fachabteilungs-Phase stehen,
 * NICHT abschließbar: `:advance` antwortet mit 409 DEPARTMENT_FORBIDDEN, solange
 * eine Pflicht-Abteilung offen ist.
 *
 * WARUM ALLE OFFENEN ABTEILUNGEN KNÖPFE BEKOMMEN
 * ----------------------------------------------
 * Das Frontend kennt die Gruppen-Mitgliedschaft der angemeldeten Person nicht:
 * `/auth/me` liefert sie nicht mit, und `abilities` sagt nur etwas über den
 * Auftrag als Ganzes, nichts je Abteilung. Damit bleiben drei Wege:
 *
 *  1. Knöpfe nur bei „eigener" Abteilung – dafür müsste die Mitgliedschaft
 *     GERATEN werden. Rät man falsch, fehlt der Knopf genau der Person, die
 *     quittieren darf, und der Auftrag bleibt hängen. Das ist der Fehler, den
 *     dieses Paket beheben soll.
 *  2. Knöpfe für jede offene Abteilung, Entscheidung beim Server. Ein
 *     unberechtigter Klick endet mit 403 DEPARTMENT_FORBIDDEN – der wird hier
 *     als verständlicher Satz gezeigt, nicht als roher Fehler. Nichts wird
 *     geändert, nichts vorgetäuscht.
 *  3. Mitgliedschaft von außen hereinreichen, sobald sie irgendwann bekannt ist.
 *
 * Gewählt ist (2) als Standard, mit (3) als optionaler Einschränkung über
 * `myGroupIds`: `null` (Standard) heißt „unbekannt, alles anbieten"; eine Liste
 * heißt „nur diese Abteilungen bedienbar". Verbindlich ist in beiden Fällen der
 * Server (`process_access.may_complete_department`), die Oberfläche ist nur
 * Vorauswahl.
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
import {
  completeDepartment, rejectDepartment, skipDepartment,
} from '@/api/processTickets'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Live-Stand aus `ticket.responsibility.departments` (nur die aktuelle Phase). */
  departments: DepartmentState[]
  /** Gruppen-ID → Name; die Detailansicht hat die Namen über lib/processSources.ts. */
  groupName?: (id: string) => string
  /** Auftrag abgelehnt/archiviert? Dann gibt es nichts mehr zu quittieren. */
  terminal?: boolean
  /** Eigene Abteilungen, FALLS bekannt. `null` = unbekannt (siehe Docstring). */
  myGroupIds?: string[] | null
}>(), {
  groupName: undefined,
  terminal: false,
  myGroupIds: null,
})

const emit = defineEmits<{ updated: [ticket: ProcessTicketOut] }>()

const { showToast } = useToast()

/** Gruppen-ID der laufenden Anfrage – sperrt währenddessen alle Knöpfe. */
const busy = ref<string | null>(null)
const fehler = ref<string | null>(null)
/** Gruppe, für die gerade eine Notiz erfasst wird (erledigt/nicht zuständig). */
const notizFuer = ref<string | null>(null)
const notiz = ref('')
/** Gruppe, für die die Ablehnungs-Rückfrage offen steht. */
const ablehnenFuer = ref<string | null>(null)
const grund = ref('')

const fortschritt = computed(() => departmentProgress(props.departments))

const nameVon = (gid: string) => props.groupName?.(gid) || gid

/** Wird für DIESE Abteilung eine Aktion angeboten? */
function bedienbar(d: DepartmentState): boolean {
  if (props.terminal || !isDepartmentPending(d)) return false
  // null = Mitgliedschaft unbekannt → anbieten, der Server entscheidet.
  return props.myGroupIds === null || props.myGroupIds.includes(d.group)
}

const eigeneUnbekannt = computed(() =>
  props.myGroupIds === null && props.departments.some(bedienbar))

/** Offene Abteilungen zuerst: dort steht die Arbeit an. */
const sortiert = computed(() => [...props.departments].sort((a, b) =>
  Number(isDepartmentPending(b)) - Number(isDepartmentPending(a))))

function reset() {
  notizFuer.value = null
  notiz.value = ''
  ablehnenFuer.value = null
  grund.value = ''
}

// Ticketwechsel: angefangene Eingaben gehören nicht zum nächsten Auftrag.
watch(() => props.ticketId, () => { reset(); fehler.value = null })

function notizUmschalten(gid: string) {
  if (notizFuer.value === gid) { reset(); return }
  reset()
  notizFuer.value = gid
}

function ablehnenOeffnen(gid: string) {
  reset()
  ablehnenFuer.value = gid
}

/**
 * Fehler in Klartext. Der 403 ist der ERWARTETE Fall dieser Oberfläche (siehe
 * Docstring) und braucht darum einen Satz, der erklärt statt zu alarmieren.
 */
function aktionsFehler(e: unknown, gid: string): string {
  const status = (e as { response?: { status?: number } })?.response?.status
  if (status === 403 && errorCode(e) === 'DEPARTMENT_FORBIDDEN') {
    return `Nur Mitglieder von „${nameVon(gid)}“ können hier quittieren – `
      + 'bitte die zuständige Abteilung bitten oder die Aufsicht einschalten.'
  }
  return errorMessage(e, 'Die Fachabteilung konnte nicht quittiert werden')
}

async function ausfuehren(
  gid: string, aktion: () => Promise<ProcessTicketOut>, erfolg: string,
) {
  busy.value = gid
  fehler.value = null
  try {
    const ticket = await aktion()
    reset()
    showToast(erfolg)
    emit('updated', ticket)
  } catch (e) {
    fehler.value = aktionsFehler(e, gid)
  } finally {
    busy.value = null
  }
}

function erledigt(gid: string) {
  const text = notizFuer.value === gid ? notiz.value.trim() : ''
  void ausfuehren(gid, () => completeDepartment(props.ticketId, gid, text || null),
                  `${nameVon(gid)}: erledigt`)
}

function nichtZustaendig(gid: string) {
  const text = notizFuer.value === gid ? notiz.value.trim() : ''
  void ausfuehren(gid, () => skipDepartment(props.ticketId, gid, text || null),
                  `${nameVon(gid)}: als „nicht zuständig“ vermerkt`)
}

function ablehnen(gid: string) {
  const text = grund.value.trim()
  // Der Server verlangt die Begründung ohnehin (422); hier gar nicht erst senden.
  if (!text) { fehler.value = 'Bitte begründen, warum der Auftrag abgelehnt wird.'; return }
  void ausfuehren(gid, () => rejectDepartment(props.ticketId, gid, text),
                  'Auftrag abgelehnt')
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
            class="px-3 py-2.5 space-y-2">
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

            <div v-if="bedienbar(d)" class="flex items-center gap-2 shrink-0 flex-wrap">
              <button type="button" :disabled="!!busy"
                      class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                             disabled:opacity-40 transition"
                      @click="erledigt(d.group)">Erledigt</button>
              <button type="button" :disabled="!!busy"
                      class="btn-secondary !py-1.5 !text-sm"
                      title="Diese Abteilung hat hier nichts zu tun – gilt als erledigt"
                      @click="nichtZustaendig(d.group)">Nicht zuständig</button>
              <button type="button" :disabled="!!busy"
                      class="px-3 py-1.5 rounded-xl text-sm border border-red-300 text-red-600
                             hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40 transition"
                      @click="ablehnenOeffnen(d.group)">Ablehnen …</button>
              <button type="button" :disabled="!!busy"
                      class="text-xs text-gray-500 dark:text-gray-400 hover:underline disabled:opacity-40"
                      @click="notizUmschalten(d.group)">
                {{ notizFuer === d.group ? 'Notiz verwerfen' : 'Notiz' }}
              </button>
            </div>
          </div>

          <!-- Notiz zu „erledigt"/„nicht zuständig" (freiwillig, landet im Verlauf) -->
          <div v-if="notizFuer === d.group && ablehnenFuer !== d.group">
            <textarea v-model="notiz" rows="2" class="afi w-full"
                      placeholder="Notiz (optional) – steht anschließend im Verlauf" />
            <p class="text-[11px] text-gray-400 mt-1">
              Die Notiz sieht jede Person mit Leserecht auf diesen Auftrag.
            </p>
          </div>

          <!-- Ablehnen: Rückfrage MIT Tragweite, Begründung ist Pflicht -->
          <div v-if="ablehnenFuer === d.group"
               class="rounded-xl border border-red-300 dark:border-red-500/40
                      bg-red-50 dark:bg-red-900/20 p-3 space-y-2">
            <p class="text-sm font-medium text-red-800 dark:text-red-200">
              Den GESAMTEN Auftrag ablehnen?
            </p>
            <p class="text-xs text-red-700 dark:text-red-300">
              Das lehnt nicht nur den Teil von „{{ nameVon(d.group) }}“ ab, sondern beendet
              den ganzen Auftrag. Die anderen Fachabteilungen kommen dann nicht mehr zum Zug;
              die Ersteller:in wird per Mail informiert. Nur die Aufsicht kann den Auftrag
              wieder aufnehmen.
            </p>
            <textarea v-model="grund" rows="3" class="afi w-full"
                      placeholder="Begründung (Pflicht) – geht an die Ersteller:in und in den Verlauf" />
            <div class="flex items-center gap-2 flex-wrap">
              <button type="button" :disabled="!!busy || !grund.trim()"
                      class="px-3 py-1.5 rounded-xl text-sm text-white bg-red-600 hover:bg-red-700
                             disabled:opacity-40 transition"
                      @click="ablehnen(d.group)">
                {{ busy === d.group ? 'Wird abgelehnt …' : 'Auftrag endgültig ablehnen' }}
              </button>
              <button type="button" :disabled="!!busy" class="btn-secondary !py-1.5 !text-sm"
                      @click="reset()">Abbrechen</button>
              <span v-if="!grund.trim()" class="text-[11px] text-red-700 dark:text-red-300">
                Ohne Begründung nicht möglich.
              </span>
            </div>
          </div>
        </li>
      </ul>

      <p v-if="eigeneUnbekannt" class="text-[11px] text-gray-400 mt-2">
        Quittieren darf nur, wer in der jeweiligen Abteilung ist. Welche das sind, weiß
        diese Ansicht nicht – deshalb stehen die Schaltflächen bei jeder offenen
        Abteilung; geprüft wird beim Klick.
      </p>
    </template>
  </div>
</template>

