<script setup lang="ts">
/**
 * Katalog der veröffentlichten Prozesse – der Weg zu einem PROZESS-Ticket
 * („Neues Prozess-Ticket" in der Navigation).
 *
 * Ersetzt die früheren 10 fest verdrahteten Kacheln: was hier steht, kommt
 * ausschließlich aus `GET /processes`. Wird ein Prozess veröffentlicht, erscheint
 * er ohne Frontend-Änderung; wird er zurückgezogen, verschwindet er.
 *
 * EINE Ausnahme: das Basis-Ticket. Es hat mit „Neues Ticket" seinen eigenen Knopf
 * in der Navigation und stünde hier ein zweites Mal – warum der Schlüssel dafür
 * hart verdrahtet ist, steht in lib/basisTicket.ts.
 *
 * Ob jemand anlegen darf, entscheidet AUSSCHLIESSLICH der Server (`may_create`
 * je Prozess, gespeist aus `createPermissions` der Definition). Das Frontend
 * kennt die Gruppen-Mitgliedschaft nicht und darf es nicht nachbauen. Kacheln
 * ohne Recht bleiben sichtbar, aber deaktiviert – so ist erkennbar, dass es den
 * Prozess gibt und man ihn beantragen kann, statt dass er unerklärlich fehlt.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { listProcesses } from '@/api/processes'
import { BASIS_TICKET_PATH, withoutBasisTicket } from '@/lib/basisTicket'
import { errorMessage } from '@/lib/processErrors'
import type { ProcessOut } from '@/types/process'

const router = useRouter()

const loading = ref(true)
const loadError = ref<string | null>(null)
const catalog = ref<ProcessOut[]>([])
const search = ref('')

/** Fällt `may_create` weg (älteres Backend), gilt der Prozess als anlegbar –
 *  der Server weist es notfalls mit 403 ab, aber wir sperren nichts vorsorglich
 *  aus, was erlaubt sein könnte. */
function darfAnlegen(p: ProcessOut): boolean {
  return p.may_create !== false
}

/** Alles außer dem Basis-Ticket – das hat seinen eigenen Einstieg. */
const prozesse = computed(() => withoutBasisTicket(catalog.value))

const gefiltert = computed(() => {
  const q = search.value.toLowerCase().trim()
  return prozesse.value.filter(
    (p) => !q || p.name.toLowerCase().includes(q) || p.key.toLowerCase().includes(q)
      || (p.description || '').toLowerCase().includes(q),
  )
})

/** Anlegbare zuerst – wer arbeiten will, soll nicht an gesperrten Kacheln vorbeiscrollen. */
const kacheln = computed(() =>
  [...gefiltert.value].sort((a, b) => Number(darfAnlegen(b)) - Number(darfAnlegen(a))),
)

const keinesAnlegbar = computed(
  () => prozesse.value.length > 0 && !prozesse.value.some(darfAnlegen),
)

function oeffnen(p: ProcessOut) {
  if (!darfAnlegen(p)) return
  router.push(`/prozess-auftraege/neu/${encodeURIComponent(p.key)}`)
}

onMounted(async () => {
  try {
    catalog.value = await listProcesses()
  } catch (e) {
    loadError.value = errorMessage(e, 'Prozesse konnten nicht geladen werden')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout title="Neues Prozess-Ticket">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else class="max-w-4xl mx-auto space-y-6">

      <div>
        <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">
          Neues Prozess-Ticket anlegen
        </h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">Wähle den passenden Prozess aus.</p>
      </div>

      <!-- Info: Was ist ein Prozess-Ticket? -->
      <div class="flex items-start gap-3 rounded-2xl border border-[#3EAAB8]/25 bg-[#3EAAB8]/[0.06] p-4">
        <span class="text-lg leading-none mt-0.5">ℹ️</span>
        <p class="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
          <span class="font-semibold text-gray-900 dark:text-white">Ein Prozess-Ticket</span>
          folgt einem festgelegten Ablauf: die Schritte (Antrag, Freigaben und Durchführung durch
          die zuständigen Fachabteilungen) sind im Prozess hinterlegt, sodass nichts vergessen wird
          und jeder Vorgang gleich abläuft. Passt nichts davon, ist
          <button @click="router.push(BASIS_TICKET_PATH)"
                  class="text-[#3EAAB8] font-medium hover:underline">„Neues Ticket"</button>
          der richtige Weg – ein einfaches Ticket ohne festen Ablauf.
        </p>
      </div>

      <div v-if="loadError"
           class="rounded-2xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                  px-4 py-3 text-sm text-red-800 dark:text-red-200">
        {{ loadError }}
      </div>

      <!-- Suche -->
      <div v-if="prozesse.length > 1" class="relative">
        <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
             fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input v-model="search" placeholder="Prozess suchen…"
               class="w-full rounded-xl border border-gray-200 dark:border-white/10
                      bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                      placeholder-gray-400 pl-10 pr-4 py-3 text-sm
                      focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition" />
      </div>

      <!-- Hinweis, wenn es gar keine Kachel zum Klicken gibt -->
      <p v-if="keinesAnlegbar" class="text-sm text-gray-500 dark:text-gray-400">
        Für keinen der veröffentlichten Prozesse liegt bei dir das Recht zum Anlegen.
        Wende dich an die Administration, wenn du einen davon brauchst.
      </p>

      <!-- Prozess-Kacheln -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <button v-for="p in kacheln" :key="p.key"
                @click="oeffnen(p)"
                :disabled="!darfAnlegen(p)"
                class="flex items-start gap-4 p-5 rounded-2xl text-left
                       border transition-all duration-150"
                :class="darfAnlegen(p)
                  ? 'bg-white dark:bg-[#212B3A] border-gray-200/80 dark:border-white/[0.09] hover:border-[#3EAAB8]/40 hover:shadow-md cursor-pointer group'
                  : 'bg-gray-50 dark:bg-[#1A2130] border-gray-100 dark:border-white/[0.05] opacity-50 cursor-not-allowed'
                ">
          <!-- Symbol aus der Definition; ohne Symbol ein neutraler Platzhalter,
               damit das Raster nicht verrutscht. -->
          <span class="text-2xl mt-0.5" :class="darfAnlegen(p) ? '' : 'grayscale'">{{ p.icon || '📄' }}</span>
          <div class="min-w-0">
            <p class="text-sm font-semibold transition-colors"
               :class="darfAnlegen(p)
                 ? 'text-gray-900 dark:text-white group-hover:text-[#3EAAB8]'
                 : 'text-gray-400 dark:text-gray-500'">
              {{ p.name }}
            </p>
            <!-- Erklärtext aus der Definition: ohne ihn müsste man den Prozess
                 öffnen, um zu erfahren, wofür er da ist. -->
            <p v-if="p.description" class="text-xs mt-1 line-clamp-2"
               :class="darfAnlegen(p) ? 'text-gray-500 dark:text-gray-400'
                                      : 'text-gray-400 dark:text-gray-600'">
              {{ p.description }}
            </p>
            <p v-if="!darfAnlegen(p)"
               class="text-[10px] text-gray-400 dark:text-gray-600 mt-1.5 uppercase tracking-wider font-medium">
              Keine Berechtigung
            </p>
          </div>
          <svg v-if="darfAnlegen(p)"
               class="w-5 h-5 text-gray-300 dark:text-gray-600 flex-shrink-0 ml-auto mt-1
                      group-hover:text-[#3EAAB8] transition-colors"
               viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
          <svg v-else class="w-4 h-4 text-gray-300 dark:text-gray-600 flex-shrink-0 ml-auto mt-1.5"
               viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
        </button>
      </div>

      <p v-if="!prozesse.length && !loadError" class="text-center text-sm text-gray-400 italic py-8">
        Es ist noch kein Prozess mit festem Ablauf veröffentlicht.
      </p>
      <p v-else-if="!kacheln.length" class="text-center text-sm text-gray-400 italic py-8">
        Kein passender Prozess gefunden.
      </p>
    </div>
  </AppLayout>
</template>
