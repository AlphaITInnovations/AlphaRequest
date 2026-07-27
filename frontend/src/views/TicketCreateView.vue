<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'

const router = useRouter()
const loading = ref(true)
const allowed = ref<string[]>([])
const search  = ref('')

const ticketTypes = [
  { key: 'onboarding',               icon: '🔑', label: 'Onboarding Mitarbeiter:innen',  desc: 'Neuen Mitarbeitenden einstellen und onboarden – von den Einstellungsdaten bis zur Durchführung.' },
  { key: 'zugang-sperren',           icon: '🔒', label: 'Offboarding Mitarbeiter:innen',  desc: 'Zugänge sperren, Geräte zurücknehmen, Accounts deaktivieren.' },
  { key: 'hardware',                 icon: '📦', label: 'Hardwarebestellung',              desc: 'Notebooks, Monitore, Peripherie und weitere Hardware bestellen.' },
  { key: 'niederlassung-anmelden',   icon: '🏢', label: 'Niederlassung anmelden',          desc: 'Neue Niederlassung anmelden, IT und Marketing vorbereiten.' },
  { key: 'niederlassung-umzug',      icon: '🔄', label: 'Niederlassung umziehen',          desc: 'Standortwechsel einer Niederlassung koordinieren.' },
  { key: 'niederlassung-schliessen', icon: '❌', label: 'Niederlassung schließen',         desc: 'Standort abmelden und alle verbundenen Dienste beenden.' },
  { key: 'marketing-stellenanzeige', icon: '📄', label: 'Marketing – Stellenanzeige',      desc: 'Stellenanzeige über Talention-Kampagne schalten.' },
  { key: 'hotelbuchung',             icon: '🏨', label: 'Hotelbuchung',                    desc: 'Hotelzimmer für Dienstreisen buchen lassen.' },
]

// Der Onboarding-Sammel-Eintrag ist aktiv, wenn EINE der beiden Varianten erlaubt ist.
const einstellungAllowed  = computed(() => allowed.value.includes('einstellung'))
const onboardingP2Allowed = computed(() => allowed.value.includes('zugang-beantragen'))

const filteredTypes = computed(() => {
  const q = search.value.toLowerCase().trim()
  return ticketTypes
    .filter(t => !q || t.label.toLowerCase().includes(q) || t.desc.toLowerCase().includes(q))
    .map(t => ({
      ...t,
      enabled: t.key === 'onboarding'
        ? (einstellungAllowed.value || onboardingP2Allowed.value)
        : allowed.value.includes(t.key),
    }))
})

// Start-Modal für Onboarding: erst Variante wählen, dann zum passenden Formular.
const showOnboarding = ref(false)

function openNew(key: string) {
  if (key === 'onboarding') { showOnboarding.value = true; return }
  router.push(`/tickets/new/${key}`)
}

function chooseOnboarding(type: 'einstellung' | 'zugang-beantragen') {
  showOnboarding.value = false
  router.push(`/tickets/new/${type}`)
}

onMounted(async () => {
  try {
    const res = await client.get<{ data: { allowed_ticket_types: string[] } }>('/dashboard')
    allowed.value = res.data.data.allowed_ticket_types
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
        <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">Neues Prozess-Ticket erstellen</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1 text-sm">Wähle den passenden Auftragstyp aus.</p>
      </div>

      <!-- Info: Was ist ein Prozess-Ticket? -->
      <div class="flex items-start gap-3 rounded-2xl border border-[#3EAAB8]/25 bg-[#3EAAB8]/[0.06] p-4">
        <span class="text-lg leading-none mt-0.5">ℹ️</span>
        <p class="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
          <span class="font-semibold text-gray-900 dark:text-white">Ein Prozess-Ticket</span>
          ist ein Ticket mit standardisiertem Ablauf für wiederkehrende Aufgaben – die einzelnen
          Schritte (Antrag, Freigaben und Durchführung durch die zuständigen Fachabteilungen) sind
          fest vorgegeben, sodass nichts vergessen wird und jeder Vorgang gleich abläuft.
        </p>
      </div>

      <!-- Suche -->
      <div class="relative">
        <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
             fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input v-model="search" placeholder="Auftragstyp suchen…"
               class="w-full rounded-xl border border-gray-200 dark:border-white/10
                      bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                      placeholder-gray-400 pl-10 pr-4 py-3 text-sm
                      focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition" />
      </div>

      <!-- Auftragstypen Grid -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <button v-for="t in filteredTypes" :key="t.key"
                @click="t.enabled && openNew(t.key)"
                :disabled="!t.enabled"
                class="flex items-start gap-4 p-5 rounded-2xl text-left
                       border transition-all duration-150"
                :class="t.enabled
                  ? 'bg-white dark:bg-[#212B3A] border-gray-200/80 dark:border-white/[0.09] hover:border-[#3EAAB8]/40 hover:shadow-md cursor-pointer group'
                  : 'bg-gray-50 dark:bg-[#1A2130] border-gray-100 dark:border-white/[0.05] opacity-50 cursor-not-allowed'
                ">
          <span class="text-2xl mt-0.5" :class="t.enabled ? '' : 'grayscale'">{{ t.icon }}</span>
          <div class="min-w-0">
            <p class="text-sm font-semibold transition-colors"
               :class="t.enabled
                 ? 'text-gray-900 dark:text-white group-hover:text-[#3EAAB8]'
                 : 'text-gray-400 dark:text-gray-500'">
              {{ t.label }}
            </p>
            <p class="text-xs mt-1 line-clamp-2"
               :class="t.enabled ? 'text-gray-500 dark:text-gray-400' : 'text-gray-300 dark:text-gray-600'">
              {{ t.desc }}
            </p>
            <p v-if="!t.enabled" class="text-[10px] text-gray-400 dark:text-gray-600 mt-1.5 uppercase tracking-wider font-medium">
              Keine Berechtigung
            </p>
          </div>
          <svg v-if="t.enabled"
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

      <p v-if="filteredTypes.length === 0" class="text-center text-sm text-gray-400 italic py-8">
        Kein passender Auftragstyp gefunden.
      </p>
    </div>

    <!-- ── Start-Modal: Onboarding-Variante wählen ── -->
    <Teleport to="body">
      <div v-if="showOnboarding"
           class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50" @click="showOnboarding = false" />
        <div class="relative w-full max-w-lg rounded-2xl bg-white dark:bg-[#212B3A]
                    border border-gray-200 dark:border-white/10 shadow-xl p-6 space-y-4">
          <div>
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">Onboarding starten</h3>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Wo möchtest du beginnen?</p>
          </div>

          <div class="space-y-3">
            <!-- Prozess 1 -->
            <button @click="einstellungAllowed && chooseOnboarding('einstellung')"
                    :disabled="!einstellungAllowed"
                    class="w-full flex items-start gap-3 p-4 rounded-2xl text-left border transition-all duration-150"
                    :class="einstellungAllowed
                      ? 'bg-white dark:bg-[#263040] border-gray-200/80 dark:border-white/[0.09] hover:border-[#3EAAB8]/40 hover:shadow-md cursor-pointer group'
                      : 'bg-gray-50 dark:bg-[#1A2130] border-gray-100 dark:border-white/[0.05] opacity-50 cursor-not-allowed'">
              <span class="text-xl mt-0.5">🧑‍💼</span>
              <div class="min-w-0">
                <p class="text-sm font-semibold"
                   :class="einstellungAllowed ? 'text-gray-900 dark:text-white group-hover:text-[#3EAAB8]' : 'text-gray-400'">
                  Einstellung Mitarbeiter:in
                </p>
                <p class="text-xs mt-1 text-gray-500 dark:text-gray-400">
                  Von den Einstellungsdaten bis zum Versand des Arbeitsvertrags.
                </p>
                <p v-if="!einstellungAllowed" class="text-[10px] text-gray-400 mt-1.5 uppercase tracking-wider font-medium">
                  Keine Berechtigung
                </p>
              </div>
            </button>

            <!-- Prozess 2 -->
            <button @click="onboardingP2Allowed && chooseOnboarding('zugang-beantragen')"
                    :disabled="!onboardingP2Allowed"
                    class="w-full flex items-start gap-3 p-4 rounded-2xl text-left border transition-all duration-150"
                    :class="onboardingP2Allowed
                      ? 'bg-white dark:bg-[#263040] border-gray-200/80 dark:border-white/[0.09] hover:border-[#3EAAB8]/40 hover:shadow-md cursor-pointer group'
                      : 'bg-gray-50 dark:bg-[#1A2130] border-gray-100 dark:border-white/[0.05] opacity-50 cursor-not-allowed'">
              <span class="text-xl mt-0.5">📨</span>
              <div class="min-w-0">
                <p class="text-sm font-semibold"
                   :class="onboardingP2Allowed ? 'text-gray-900 dark:text-white group-hover:text-[#3EAAB8]' : 'text-gray-400'">
                  Onboarding nach Vertragsrücklauf
                </p>
                <p class="text-xs mt-1 text-gray-500 dark:text-gray-400">
                  Start nach Rücksendung des unterschriebenen Arbeitsvertrags.
                </p>
                <p v-if="!onboardingP2Allowed" class="text-[10px] text-gray-400 mt-1.5 uppercase tracking-wider font-medium">
                  Keine Berechtigung
                </p>
              </div>
            </button>
          </div>

          <div class="flex justify-end pt-1">
            <button @click="showOnboarding = false"
                    class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                           text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
              Abbrechen
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>