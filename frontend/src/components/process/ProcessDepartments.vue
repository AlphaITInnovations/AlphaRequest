<script setup lang="ts">
/**
 * Fachabteilungen einer Fachabteilungs-Phase – reine ANZEIGE: pro Abteilung der
 * Stand (offen / erledigt / …), wer wann quittiert hat und eine etwaige Notiz.
 *
 * Abgeschlossen wird NICHT hier, sondern unten über den grünen Knopf
 * „Fachabteilung abschließen" (ProcessTicketDetailView) – der schließt die
 * EIGENE Abteilung ab und schaltet, wenn es die letzte Pflicht-Abteilung war,
 * die Phase weiter. Diese Anzeige zeigt nur, wie weit die Phase ist.
 */
import { computed } from 'vue'
import {
  departmentProgress, departmentStatusLabel, departmentTone, isDepartmentPending,
  isRequired, requiredLabel, type DepartmentState,
} from '@/lib/processDepartments'
import { absoluteTime, relativeTime } from '@/lib/processEventLabels'

const props = withDefaults(defineProps<{
  /** Live-Stand aus `ticket.responsibility.departments` (nur die aktuelle Phase). */
  departments: DepartmentState[]
  /** Gruppen-ID → Name; die Detailansicht hat die Namen über lib/processSources.ts. */
  groupName?: (id: string) => string
}>(), {
  groupName: undefined,
})

const fortschritt = computed(() => departmentProgress(props.departments))

const nameVon = (gid: string) => props.groupName?.(gid) || gid

/** Offene Abteilungen zuerst: dort steht die Arbeit an. */
const sortiert = computed(() => [...props.departments].sort((a, b) =>
  Number(isDepartmentPending(b)) - Number(isDepartmentPending(a))))

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
      <p v-if="fortschritt.openRequired" class="text-xs text-gray-500 dark:text-gray-400 mb-3">
        Der Phasenabschluss wartet noch auf
        {{ fortschritt.openRequired }} Pflicht-Abteilung{{ fortschritt.openRequired === 1 ? '' : 'en' }}.
      </p>
      <p v-else class="text-xs text-green-700 dark:text-green-300 mb-3">
        Alle Pflicht-Abteilungen sind fertig.
      </p>

      <ul class="divide-y divide-gray-100 dark:divide-white/[0.06] rounded-xl
                 border border-gray-200 dark:border-white/10 overflow-hidden">
        <li v-for="d in sortiert" :key="d.group" class="px-3 py-2.5">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-sm text-gray-800 dark:text-gray-100 truncate flex-1 min-w-0"
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
        </li>
      </ul>
    </template>
  </div>
</template>
