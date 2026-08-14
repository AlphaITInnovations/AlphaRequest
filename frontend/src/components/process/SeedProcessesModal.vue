<script setup lang="ts">
/**
 * „Mitgelieferte Prozesse einspielen“ – der Ersatz für den Server-Shell-Befehl
 * (`python -m backend.scripts.seed_processes --commit`).
 *
 * ZWEI SCHRITTE, IMMER: erst der Trockenlauf (`commit: false`, schreibt nichts),
 * dann eine ausdrückliche Bestätigung. Der Trockenlauf ist der Sinn der Sache –
 * er nennt fehlende Fachabteilungen und die übernommenen Erstellrechte, BEVOR
 * zehn Prozesse in der Datenbank stehen. Deshalb gibt es hier keinen Weg, der
 * direkt schreibt: ohne Bericht ist der Einspielen-Knopf nicht bedienbar.
 *
 * Ändert sich die Rechte-Einstellung, verfällt der Bericht: er beschreibt dann
 * einen anderen Lauf als den, der geschrieben würde.
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { seedProcesses } from '@/api/processes'
import { errorMessage } from '@/lib/processErrors'
import { normalizeSeedReport, permissionsSummary } from '@/lib/processSeedReport'
import type { SeedSummary, SeedTone } from '@/lib/processSeedReport'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  close: []
  /** Es wurde tatsächlich geschrieben – die Liste im Panel ist veraltet. */
  seeded: []
}>()

const report  = ref<SeedSummary | null>(null)
const running = ref<'dry' | 'commit' | null>(null)
const error   = ref<string | null>(null)
/** Erstellrechte aus dem Alt-System übernehmen (CLI: ohne --skip-permissions). */
const withPermissions = ref(true)

const committed = computed(() => !!report.value?.commit)
const canCommit = computed(() =>
  !running.value && !!report.value && !report.value.commit && !report.value.nothingToDo)

const TONE_BADGE: Record<SeedTone, string> = {
  ok:    'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  info:  'bg-[#3EAAB8]/15 text-[#2B7D89] dark:bg-[#3EAAB8]/20 dark:text-[#7FD3DD]',
  muted: 'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
  error: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}

function reset() {
  report.value = null
  running.value = null
  error.value = null
  withPermissions.value = true
}

function close() {
  if (running.value) return
  emit('close')
}

function onWindowKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape') close()
}

watch(() => props.open, (open) => {
  if (open) {
    reset()
    window.addEventListener('keydown', onWindowKey)
  } else {
    window.removeEventListener('keydown', onWindowKey)
  }
})

onUnmounted(() => window.removeEventListener('keydown', onWindowKey))

// Der Bericht gilt nur für die Einstellung, mit der er gefahren wurde.
watch(withPermissions, () => { if (!committed.value) report.value = null })

async function run(commit: boolean) {
  if (commit && !canCommit.value) return
  running.value = commit ? 'commit' : 'dry'
  error.value = null
  try {
    const raw = await seedProcesses({ commit, skipPermissions: !withPermissions.value })
    report.value = normalizeSeedReport(raw)
    if (commit) emit('seeded')
  } catch (e) {
    error.value = errorMessage(e, commit
      ? 'Einspielen fehlgeschlagen'
      : 'Der Trockenlauf ist fehlgeschlagen')
  } finally {
    running.value = null
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
           @click.self="close()">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-2xl p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]
                    max-h-[90vh] overflow-y-auto">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">
            Mitgelieferte Prozesse einspielen
          </h3>

          <p class="text-sm text-gray-600 dark:text-gray-300">
            Mit der Anwendung werden Prozess-Definitionen ausgeliefert (Onboarding, Bestellung,
            …). Dieser Lauf legt sie an und veröffentlicht sie. Vorhandene Schlüssel werden
            <span class="font-medium">nie überschrieben</span>, System-Prozesse lässt er liegen –
            die pflegt die Anwendung selbst.
          </p>

          <!-- Was der Lauf NICHT tut. Beides führt sonst zu Rückfragen: Mails, die
               nicht ankommen, und Prozesse, die nur Admins anlegen können. -->
          <div class="rounded-xl border border-amber-200 dark:border-amber-500/30
                      bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm
                      text-amber-900 dark:text-amber-200 space-y-1">
            <p class="font-medium">Was danach noch von Hand zu tun ist:</p>
            <ul class="list-disc pl-5 space-y-1 text-[13px]">
              <li>
                Fachabteilungen, die der Lauf neu anlegt, haben
                <span class="font-medium">keine Verteiler-Adresse</span> – an sie geht dann keine
                Mail. Die Adressen werden unter „Fachabteilungen“ nachgetragen.
              </li>
              <li>
                Wer einen Prozess anlegen darf, wird aus dem Alt-System übernommen. Gibt es dort
                keine Rechte (frische Installation), bleibt es bei
                <span class="font-medium">„nur Admins“</span>; das wird im Prozess-Editor unter
                „Erstellrechte“ gesetzt.
              </li>
            </ul>
          </div>

          <!-- Option -->
          <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input type="checkbox" v-model="withPermissions" :disabled="!!running || committed"
                   class="mt-0.5 accent-[#3EAAB8]" />
            <span>
              Erstellrechte aus dem Alt-System übernehmen
              <span class="block text-xs text-gray-400">
                Abgewählt starten alle Prozesse mit „nur Admins“.
              </span>
            </span>
          </label>

          <p v-if="error"
             class="rounded-xl border border-red-300 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                    px-4 py-3 text-sm text-red-800 dark:text-red-300">
            {{ error }}
          </p>

          <!-- Bericht -->
          <div v-if="report" class="space-y-3">
            <div class="rounded-xl px-4 py-3 text-sm font-medium border"
                 :class="report.commit
                   ? 'border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200'
                   : 'border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#1A2130] text-gray-700 dark:text-gray-200'">
              {{ report.headline }}
              <!-- Nur ohne Fehler: bei Fehlern ist „bereits vorhanden“ die falsche
                   Erklärung dafür, dass nichts angelegt würde. -->
              <p v-if="!report.commit && report.nothingToDo && !report.hasErrors"
                 class="text-xs font-normal mt-1">
                Alle mitgelieferten Prozesse sind bereits vorhanden – es gibt nichts einzuspielen.
              </p>
              <p v-else-if="!report.commit && report.hasErrors" class="text-xs font-normal mt-1">
                Fehlerhafte Definitionen werden nicht eingespielt – die übrigen schon.
              </p>
            </div>

            <!-- Gruppen -->
            <div class="text-xs space-y-1.5 text-gray-600 dark:text-gray-300">
              <p v-if="report.requiredGroups.length">
                <span class="text-gray-400">Pflichtgruppen:</span>
                {{ report.requiredGroups.join(', ') }}
              </p>
              <p v-if="report.missingGroups.length" class="text-amber-700 dark:text-amber-300">
                <span class="font-medium">Fehlen noch:</span>
                {{ report.missingGroups.join(', ') }} – werden beim Einspielen angelegt,
                zunächst ohne Verteiler-Adresse.
              </p>
              <p v-if="report.createdGroups.length" class="text-green-700 dark:text-green-300">
                <span class="font-medium">Neu angelegte Fachabteilungen:</span>
                {{ report.createdGroups.join(', ') }} – bitte Verteiler-Adressen nachtragen.
              </p>
            </div>

            <!-- Je Prozess -->
            <div v-if="report.rows.length" class="space-y-1.5">
              <div v-for="r in report.rows" :key="r.title"
                   class="rounded-xl border border-gray-200 dark:border-white/10
                          bg-white dark:bg-[#263040] px-3 py-2">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-mono text-xs text-gray-700 dark:text-gray-200">{{ r.title }}</span>
                  <span class="text-[11px] font-medium px-2 py-0.5 rounded-full" :class="TONE_BADGE[r.tone]">
                    {{ r.label }}
                  </span>
                  <span v-if="r.isSystem"
                        class="text-[11px] font-medium px-2 py-0.5 rounded-full
                               bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                    System
                  </span>
                  <span v-if="r.message" class="text-xs text-gray-500 dark:text-gray-400">
                    {{ r.message }}
                  </span>
                </div>
                <p v-if="permissionsSummary(r.permissions)" class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Erstellrechte: {{ permissionsSummary(r.permissions) }}
                </p>
                <p v-for="gid in r.ineffectiveGroups" :key="gid"
                   class="text-xs text-amber-700 dark:text-amber-300 mt-1">
                  Gruppe {{ gid }} wird nicht übernommen – das Anlegerecht kennt nur interne
                  Fachabteilungen, keine AD-Gruppen.
                </p>
                <p v-for="(w, i) in r.warnings" :key="`w${i}`"
                   class="text-xs text-amber-700 dark:text-amber-300 mt-1">
                  Warnung: {{ w }}
                </p>
              </div>
            </div>
            <p v-else class="text-sm text-gray-400 italic">
              Der Lauf hat keine mitgelieferte Definition gefunden.
            </p>
          </div>

          <!-- Aktionen -->
          <div class="flex flex-wrap justify-end gap-3 pt-2">
            <button @click="close()" :disabled="!!running"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 disabled:opacity-50 transition">
              {{ committed ? 'Schließen' : 'Abbrechen' }}
            </button>
            <button v-if="!committed" @click="run(false)" :disabled="!!running"
                    class="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed">
              {{ running === 'dry' ? 'Trockenlauf läuft…'
                : report ? 'Trockenlauf wiederholen' : 'Trockenlauf starten' }}
            </button>
            <button v-if="!committed" @click="run(true)" :disabled="!canCommit"
                    :title="report ? undefined : 'Erst den Trockenlauf ansehen'"
                    class="btn-primary">
              {{ running === 'commit' ? 'Spiele ein…' : 'Jetzt einspielen' }}
            </button>
          </div>
          <p v-if="!committed && !report" class="text-xs text-gray-400 text-right">
            Eingespielt wird erst nach dem Trockenlauf – und erst mit dem zweiten Knopf.
          </p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
