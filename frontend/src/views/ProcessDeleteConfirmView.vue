<script setup lang="ts">
/**
 * Bestätigungsseite für das Löschen eines ganzen Prozesses.
 *
 * Aufgerufen über den Link aus der Bestätigungs-Mail an die Admin-Adresse
 * (`/prozesse/loeschen?token=…`).
 *
 * ANMELDUNG ERFORDERLICH – bewusst anders als beim Freigabe-Link. Dort hat die
 * entscheidende Person absichtlich keinen Systemzugang; hier ist jede:r
 * Anfordernde ohnehin Admin. Eine Seite, die auf Vorzeigen eines Tokens einen
 * Prozess mit allen Aufträgen löscht, wäre für eine weitergeleitete Mail eine viel
 * zu große Angriffsfläche. Die Mail ist der ZWEITE Kanal, nicht die Berechtigung.
 *
 * Der Umfang wird VOR dem Bestätigen vom Server geholt und angezeigt – niemand
 * soll auf „Löschen" klicken, ohne die Zahl der betroffenen Aufträge zu sehen.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { confirmProcessDelete, previewProcessDelete } from '@/api/processes'
import type { ProcessDeletePreview } from '@/types/process'
import { errorCode, errorMessage } from '@/lib/processErrors'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()

const token = computed(() => String(route.query.token || ''))
const loading = ref(true)
const busy = ref(false)
const vorschau = ref<ProcessDeletePreview | null>(null)
const fehler = ref<string | null>(null)
const erledigt = ref<{ versions: number; tickets: number } | null>(null)

/** Meldungen, die erklären, WARUM der Link nicht mehr gilt. */
const HINWEIS: Record<string, string> = {
  PROCESS_DELETE_EXPIRED:
    'Der Bestätigungs-Link ist abgelaufen. Bitte die Löschung erneut anfordern.',
  PROCESS_DELETE_SUPERSEDED:
    'Der Prozess hat sich seit der Anforderung geändert. Bitte erneut anfordern, '
    + 'damit die Bestätigung den aktuellen Stand zeigt.',
  PROCESS_DELETE_NOT_FOUND:
    'Diesen Prozess gibt es nicht mehr – vielleicht wurde er bereits gelöscht.',
  PROCESS_DELETE_INVALID: 'Der Bestätigungs-Link ist ungültig.',
}

async function laden() {
  loading.value = true
  fehler.value = null
  try {
    vorschau.value = await previewProcessDelete(token.value)
  } catch (e) {
    fehler.value = HINWEIS[errorCode(e) || ''] || errorMessage(e, 'Der Link ist nicht gültig.')
    vorschau.value = null
  } finally {
    loading.value = false
  }
}

async function loeschen() {
  const v = vorschau.value
  if (!v) return
  if (!confirm(
    `„${v.name}" endgültig löschen?\n\n`
    + `• Definition mit ${v.versions.length} Version(en)\n`
    + `• ${v.tickets} Auftrag/Aufträge samt Verlauf, Beobachter:innen und Anhängen\n\n`
    + 'Das lässt sich NICHT rückgängig machen.')) return
  busy.value = true
  try {
    const res = await confirmProcessDelete(token.value)
    erledigt.value = { versions: res.versions_deleted, tickets: res.tickets_deleted }
    showToast(`„${v.name}" gelöscht`)
  } catch (e) {
    fehler.value = HINWEIS[errorCode(e) || ''] || errorMessage(e, 'Löschen fehlgeschlagen')
  } finally {
    busy.value = false
  }
}

onMounted(laden)
</script>

<template>
  <AppLayout>
    <div class="max-w-2xl mx-auto px-4 py-8">
      <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 mb-1">
        Löschung bestätigen
      </h1>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Aus der Bestätigungs-Mail an die Admin-Adresse.
      </p>

      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <!-- Ergebnis -->
      <div v-else-if="erledigt"
           class="rounded-2xl border border-green-200 dark:border-green-500/30
                  bg-green-50 dark:bg-green-900/20 px-5 py-4">
        <p class="text-sm text-green-800 dark:text-green-200">
          Gelöscht: {{ erledigt.versions }} Version(en)
          <template v-if="erledigt.tickets">
            und {{ erledigt.tickets }} Auftrag/Aufträge
          </template>.
        </p>
        <button @click="router.push('/settings')"
                class="mt-3 text-sm text-[#3EAAB8] hover:underline">Zu den Einstellungen</button>
      </div>

      <!-- Link nicht (mehr) gültig -->
      <div v-else-if="fehler"
           class="rounded-2xl border border-amber-200 dark:border-amber-500/30
                  bg-amber-50 dark:bg-amber-900/20 px-5 py-4">
        <p class="text-sm text-amber-800 dark:text-amber-200">{{ fehler }}</p>
        <button @click="router.push('/settings')"
                class="mt-3 text-sm text-[#3EAAB8] hover:underline">Zu den Einstellungen</button>
      </div>

      <!-- Umfang zeigen, dann bestätigen -->
      <div v-else-if="vorschau" class="space-y-4">
        <div class="card-section">
          <h2 class="text-base font-semibold text-gray-800 dark:text-gray-100">
            {{ vorschau.name }}
          </h2>
          <p class="text-xs font-mono text-gray-400 mt-0.5">{{ vorschau.key }}</p>

          <dl class="mt-4 space-y-2 text-sm">
            <div class="flex gap-2">
              <dt class="text-gray-500 dark:text-gray-400 w-40 flex-shrink-0">Versionen</dt>
              <dd class="text-gray-800 dark:text-gray-100">
                <span v-for="v in vorschau.versions" :key="v.version" class="mr-2">
                  v{{ v.version }}
                  <span class="text-gray-400">({{ v.status }})</span>
                </span>
              </dd>
            </div>
            <div class="flex gap-2">
              <dt class="text-gray-500 dark:text-gray-400 w-40 flex-shrink-0">Aufträge</dt>
              <dd :class="vorschau.tickets
                    ? 'font-semibold text-red-600 dark:text-red-400'
                    : 'text-gray-800 dark:text-gray-100'">
                {{ vorschau.tickets }}
                <span v-if="vorschau.tickets" class="font-normal text-gray-500 dark:text-gray-400">
                  – samt Verlauf, Beobachter:innen und Anhängen
                </span>
              </dd>
            </div>
            <div v-if="vorschau.requested_by" class="flex gap-2">
              <dt class="text-gray-500 dark:text-gray-400 w-40 flex-shrink-0">Angefordert von</dt>
              <dd class="text-gray-800 dark:text-gray-100 font-mono text-xs">
                {{ vorschau.requested_by }}
              </dd>
            </div>
          </dl>
        </div>

        <div class="rounded-2xl border border-red-200 dark:border-red-500/30
                    bg-red-50 dark:bg-red-900/20 px-5 py-4">
          <p class="text-sm text-red-800 dark:text-red-200">
            Das Löschen lässt sich <strong>nicht rückgängig machen</strong>. Im Audit-Log
            bleibt nachvollziehbar, was entfernt wurde.
          </p>
        </div>

        <div class="flex items-center justify-end gap-2">
          <button @click="router.push('/settings')" class="btn-secondary text-sm">Abbrechen</button>
          <button @click="loeschen" :disabled="busy"
                  class="px-4 py-2 rounded-xl text-sm text-white bg-red-600 hover:bg-red-700
                         disabled:opacity-40 transition">
            {{ busy ? 'Wird gelöscht…' : 'Endgültig löschen' }}
          </button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
