<script setup lang="ts">
/**
 * Die Auftragstabelle der Übersicht.
 *
 * Nimmt fertige Anzeige-Zeilen (lib/overviewRow.ts) – hier wird nichts mehr
 * abgeleitet, damit die Zuordnung „ID → Name" an genau einer, testbaren Stelle
 * liegt. Sortiert wird nicht selbst: die Spaltenköpfe MELDEN nur den Wunsch, denn
 * ob dafür ein neues Fenster geladen werden muss, weiß nur die Übersicht.
 *
 * Es gibt bewusst KEINE Prioritäts-Spalte: die Priorität ist überall
 * ausgeblendet, bis geklärt ist, wie sie sinnvoll genutzt wird (Feld bleibt in
 * DB und API).
 */
import type { OverviewRow } from '@/lib/overviewRow'
import type { OverviewSortKey, SortDir } from '@/lib/overviewQuery'

const props = defineProps<{
  rows: readonly OverviewRow[]
  sortKey: OverviewSortKey
  sortDir: SortDir
  loading?: boolean
  /** Text für die leere Liste – hängt von der gewählten Sicht ab. */
  emptyText: string
  /** Archivieren-Knopf je Zeile (Manager + Admin) – verbindlich prüft der Server. */
  canArchive?: boolean
}>()

const emit = defineEmits<{
  (e: 'open', id: number): void
  (e: 'sort', key: OverviewSortKey): void
  (e: 'archive', id: number): void
}>()

/** Terminale Aufträge (archiviert/abgelehnt) haben nichts mehr zu archivieren. */
function archivierbar(r: OverviewRow): boolean {
  return !!props.canArchive && r.status !== 'archived' && r.status !== 'rejected'
}

const STATUS_CLASS: Record<string, string> = {
  in_progress: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  in_request: 'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  waiting_contract: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
  archived: 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}

function statusClass(status: string) {
  return STATUS_CLASS[status] ?? 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-400'
}

/** Pfeil nur an der aktiven Spalte – sonst wäre die Richtung eine Behauptung. */
function sortIcon(key: OverviewSortKey) {
  if (props.sortKey !== key) return ''
  return props.sortDir === 'asc' ? '▲' : '▼'
}
</script>

<template>
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm overflow-hidden">
    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-gray-100 dark:border-white/[0.06]
                     text-xs font-semibold text-gray-400 uppercase tracking-wider select-none">
            <th class="th" @click="emit('sort', 'id')">
              ID <span class="ico">{{ sortIcon('id') }}</span>
            </th>
            <th class="th" @click="emit('sort', 'title')">
              Titel <span class="ico">{{ sortIcon('title') }}</span>
            </th>
            <th class="th hidden md:table-cell" @click="emit('sort', 'owner')">
              Ersteller <span class="ico">{{ sortIcon('owner') }}</span>
            </th>
            <!-- „Zuständig" ist nicht sortierbar: der Wert kommt als ID und wird
                 erst über die nachgeladenen Namen lesbar – die Sortierung würde
                 sich beim Nachladen unter der Hand umstellen. -->
            <th class="px-4 py-3 text-left whitespace-nowrap hidden lg:table-cell">Zuständig</th>
            <th class="px-4 py-3 text-left whitespace-nowrap hidden lg:table-cell">Phase</th>
            <th class="th" @click="emit('sort', 'status')">
              Status <span class="ico">{{ sortIcon('status') }}</span>
            </th>
            <th class="th hidden sm:table-cell" @click="emit('sort', 'updated_at')">
              Geändert <span class="ico">{{ sortIcon('updated_at') }}</span>
            </th>
            <th class="px-4 py-3 text-right">Aktion</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <tr v-for="r in rows" :key="r.id" @click="emit('open', r.id)"
              class="hover:bg-gray-50 dark:hover:bg-[#263040] transition cursor-pointer">
            <td class="px-4 py-3.5 font-mono text-xs text-[#3EAAB8]">#{{ r.id }}</td>
            <td class="px-4 py-3.5">
              <p :title="r.title"
                 class="font-medium text-gray-900 dark:text-white truncate max-w-[24rem]">
                {{ r.title }}
              </p>
              <p class="text-xs text-gray-400 mt-0.5 truncate max-w-[24rem]">
                <span v-if="r.processIcon" class="mr-1">{{ r.processIcon }}</span>{{ r.processLabel }}
                · {{ r.createdAt }}
              </p>
            </td>
            <td class="px-4 py-3.5 text-gray-600 dark:text-gray-300 hidden md:table-cell">
              {{ r.ownerName }}
            </td>
            <td class="px-4 py-3.5 hidden lg:table-cell">
              <!-- Niemand zuständig heißt: der Auftrag bleibt liegen. Das muss
                   auffallen, nicht als leere Zelle untergehen. -->
              <span v-if="r.responsible.missing" :title="r.responsible.hint"
                    class="text-xs font-medium px-2.5 py-1 rounded-full whitespace-nowrap
                           bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
                Niemand zuständig
              </span>
              <template v-else>
                <p class="text-gray-600 dark:text-gray-300 truncate max-w-[12rem]"
                   :title="r.responsible.text">{{ r.responsible.text }}</p>
                <p class="text-[11px] text-gray-400">{{ r.responsible.role }}</p>
              </template>
            </td>
            <td class="px-4 py-3.5 hidden lg:table-cell">
              <span v-if="r.phaseLabel !== '—'"
                    class="text-xs font-medium px-2.5 py-1 rounded-full whitespace-nowrap
                           bg-[#3EAAB8]/10 text-[#3EAAB8]">
                {{ r.phaseLabel }}
              </span>
              <span v-else class="text-xs text-gray-400">—</span>
            </td>
            <td class="px-4 py-3.5">
              <span class="text-xs font-medium px-2.5 py-1 rounded-full whitespace-nowrap"
                    :class="statusClass(r.status)">{{ r.statusLabel }}</span>
            </td>
            <td class="px-4 py-3.5 text-gray-500 dark:text-gray-400 whitespace-nowrap hidden sm:table-cell">
              {{ r.updatedAt }}
            </td>
            <td class="px-4 py-3.5 text-right whitespace-nowrap" @click.stop>
              <button v-if="archivierbar(r)" @click="emit('archive', r.id)"
                      title="Zwangsweise abschließen (Begründung Pflicht)"
                      class="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-white/10
                             text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-white/5
                             text-xs font-medium transition whitespace-nowrap mr-1.5">
                Archivieren
              </button>
              <button @click="emit('open', r.id)"
                      class="px-3 py-1.5 rounded-xl bg-[#3EAAB8]/10 text-[#3EAAB8]
                             hover:bg-[#3EAAB8]/20 text-xs font-medium transition whitespace-nowrap">
                Details →
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="px-4 py-12 text-center text-sm text-gray-400 italic">
              {{ emptyText }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.th {
  @apply px-4 py-3 text-left cursor-pointer hover:text-[#3EAAB8] transition whitespace-nowrap;
}
.ico { @apply text-[#3EAAB8] text-[10px] ml-0.5; }
</style>
