<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const logoUrl = '/static/logo.png'
const auth = useAuthStore()
const router = useRouter()

// Directus nicht erreichbar ist ein VORÜBERGEHENDER Zustand (503), „kein
// Datensatz" (403) ein dauerhafter – dafür jeweils passende Texte.
const isTemporary = computed(() => auth.accessDenied?.code === 'DIRECTUS_UNAVAILABLE')

const title = computed(() =>
  isTemporary.value ? 'Vorübergehend nicht verfügbar' : 'Kein Zugang')

const message = computed(() =>
  auth.accessDenied?.message
  || (isTemporary.value
    ? 'Die Mitarbeiterdaten sind zurzeit nicht erreichbar. Bitte später erneut anmelden.'
    : 'Zu Ihrem Konto wurde kein Mitarbeiter-Datensatz gefunden. Bitte an die Administration wenden.'))

function retry() {
  // Session besteht noch – nur neu prüfen (der Guard ruft fetchMe erneut). Greift
  // sofort, falls Directus wieder da ist bzw. der Datensatz inzwischen angelegt
  // wurde (das Backend cacht „nicht gefunden" bewusst nicht). Kein neuer Login nötig.
  router.replace('/dashboard')
}

function logout() {
  auth.logout()
}
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-white to-gray-100 dark:from-[#1E2327] dark:to-[#1E2327]
              flex items-center justify-center font-sans text-gray-900 dark:text-gray-100 p-4">
    <main class="bg-white dark:bg-[#2B3036] shadow-xl rounded-lg p-8 w-full max-w-md border
                 border-gray-100 dark:border-gray-700 text-center">

      <img :src="logoUrl" alt="Firmenlogo" class="mx-auto mb-4 h-14 w-auto" loading="lazy" />

      <!-- Warn-Icon -->
      <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full
                  bg-amber-100 dark:bg-amber-900/30">
        <svg class="h-7 w-7 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24"
             stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round"
                d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>

      <h1 class="text-xl font-semibold mb-2">{{ title }}</h1>
      <p class="text-sm text-gray-600 dark:text-gray-300 mb-6">{{ message }}</p>

      <button
        @click="retry"
        class="block text-center w-full text-white font-medium py-2.5 rounded-md transition"
        style="background-color: #3EAAB8"
        onmouseover="this.style.backgroundColor='#2B7D89'"
        onmouseout="this.style.backgroundColor='#3EAAB8'">
        Erneut versuchen
      </button>

      <button
        @click="logout"
        class="mt-3 block w-full rounded-md border border-gray-200 dark:border-white/10
               px-5 py-2.5 text-sm font-medium text-gray-600 dark:text-gray-300
               hover:bg-gray-50 dark:hover:bg-white/5 transition">
        Abmelden
      </button>

      <p class="text-center text-xs text-gray-500 dark:text-gray-400 mt-6">© AlphaConsult Gruppe</p>
    </main>
  </div>
</template>
