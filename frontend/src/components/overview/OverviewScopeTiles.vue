<script setup lang="ts">
/**
 * Die Sichten der Übersicht als Kacheln: „Alle Aufträge" und die vier
 * Arbeitslisten. Die Kacheln SIND der Filter – ein Klick stellt die Liste um.
 *
 * Die Zahlen zählen über das Arbeitsfenster (die neuesten geladenen Aufträge),
 * nicht über die gefilterte Liste: die Frage „wartet etwas auf mich?" darf sich
 * nicht ändern, nur weil unten ein Status abgewählt ist. Ist das Fenster
 * abgeschnitten, sagt es die Kachel-Zeile (`truncated`) – lieber „mindestens"
 * als eine Zahl, die vollständig aussieht und es nicht ist.
 */
import { OVERVIEW_SCOPES, SCOPE_HINT, SCOPE_LABEL, type OverviewScope } from '@/lib/overviewQuery'

const props = defineProps<{
  active: OverviewScope
  counts: Record<OverviewScope, number>
  /** Zähler beruhen auf einem abgeschnittenen Fenster → „mindestens". */
  truncated?: boolean
  /** Zähler noch nicht geladen – dann statt „0" ein Platzhalter. */
  loading?: boolean
}>()

const emit = defineEmits<{ (e: 'select', scope: OverviewScope): void }>()

/** Farbe je Sicht – dieselbe Zuordnung wie in der alten Arbeitslisten-Ansicht. */
const TON: Record<OverviewScope, string> = {
  all: 'bg-[#3EAAB8]/15 text-[#2B7D89] dark:text-[#5FD3DE]',
  assigned: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400',
  departments: 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400',
  created: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400',
  involved: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400',
}

function zahl(scope: OverviewScope): string {
  if (props.loading) return '…'
  const n = props.counts[scope] ?? 0
  // Bei abgeschnittenem Fenster ist jede Zahl eine UNTERGRENZE – das „+" sagt
  // es, statt eine Vollständigkeit zu behaupten, die das Fenster nicht hat.
  return props.truncated ? `${n}+` : String(n)
}
</script>

<template>
  <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
    <button v-for="s in OVERVIEW_SCOPES" :key="s" @click="emit('select', s)"
            class="stat" :class="active === s ? 'stat-on' : ''"
            :aria-pressed="active === s">
      <div class="flex items-center justify-between">
        <span class="stat-icon" :class="TON[s]">
          <svg v-if="s === 'all'" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2"/>
            <rect x="8" y="2" width="8" height="4" rx="1"/>
          </svg>
          <svg v-else-if="s === 'assigned'" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
          </svg>
          <svg v-else-if="s === 'departments'" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
          </svg>
          <svg v-else-if="s === 'created'" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-3-3v6m-7 5h14a2 2 0 002-2V7a2 2 0 00-2-2h-5l-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
          </svg>
          <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
          </svg>
        </span>
        <span class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">
          {{ zahl(s) }}
        </span>
      </div>
      <p class="stat-label inline-flex items-center gap-1">
        {{ SCOPE_LABEL[s] }}
        <span class="hint" @click.stop>
          <svg class="hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="9"/>
            <line x1="12" y1="11" x2="12" y2="16" stroke-linecap="round"/>
            <line x1="12" y1="7.6" x2="12.01" y2="7.6" stroke-linecap="round"/>
          </svg>
          <span class="bubble">{{ SCOPE_HINT[s] }}</span>
        </span>
      </p>
    </button>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.stat {
  @apply relative bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
         rounded-2xl p-4 text-left transition-all duration-200
         hover:z-30 hover:shadow-md hover:-translate-y-0.5 hover:border-gray-300 dark:hover:border-white/20;
}
.stat-on {
  @apply ring-2 ring-[#3EAAB8]/50 border-[#3EAAB8]/40 shadow-sm
         bg-[#3EAAB8]/[0.05] dark:bg-[#3EAAB8]/[0.08];
}
.stat-icon { @apply w-8 h-8 rounded-xl flex items-center justify-center; }
/* kräftigere Icon-Striche */
.stat-icon svg { stroke-width: 2.3px; }
.stat-label { @apply text-[13px] font-semibold text-gray-700 dark:text-gray-200 mt-2.5; }

/* Info-Icon mit Hover-Tooltip auf den Kacheln. Die Bubble wird relativ zur Karte
   (.stat = relative) zentriert und darunter gelegt – so läuft sie auch bei der
   rechten Karte nicht über den Rand. */
.hint { @apply inline-flex items-center cursor-help; }
.hint-icon { @apply w-[18px] h-[18px] text-gray-300 dark:text-gray-600 transition-colors; }
.hint:hover .hint-icon { @apply text-gray-500 dark:text-gray-300; }
.bubble {
  @apply pointer-events-none absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 w-44 sm:w-56
         rounded-lg bg-gray-900 text-gray-100 text-[11px] leading-snug px-3 py-2
         opacity-0 transition-opacity duration-150 normal-case font-normal text-left shadow-lg;
}
.hint:hover .bubble { @apply opacity-100; }
</style>
