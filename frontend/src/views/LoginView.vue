<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

const logoUrl = '/static/logo.png'
const route = useRoute()
const redirecting = ref(false)

/** Fehlercodes, mit denen der Backend-Callback nach /login?error=… zurückleitet.
 *  Ohne Anzeige wirkte der Login-Knopf so, als würde „nichts passieren". */
const ERROR_MESSAGES: Record<string, string> = {
  token_error: 'Die Anmeldung bei Microsoft konnte nicht abgeschlossen werden (kein Token erhalten). Bitte erneut versuchen.',
  login_failed: 'Beim Login ist ein Fehler aufgetreten. Bitte erneut versuchen – wenden Sie sich an die Administration, falls es weiterhin auftritt.',
  session_expired: 'Ihre Sitzung wurde beendet. Bitte melden Sie sich erneut an.',
}

const errorMessage = computed(() => {
  const code = route.query.error
  if (typeof code !== 'string' || !code) return null
  return ERROR_MESSAGES[code] || 'Anmeldung fehlgeschlagen. Bitte erneut versuchen.'
})

function startAuth() {
  redirecting.value = true
  window.location.href = '/start-auth'
}
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-white to-gray-100 dark:from-[#1E2327] dark:to-[#1E2327] flex items-center justify-center font-sans text-gray-900 dark:text-gray-100">
    <main class="bg-white dark:bg-[#2B3036] shadow-xl rounded-lg p-8 w-full max-w-md border border-gray-100 dark:border-gray-700">

      <img :src="logoUrl" alt="Firmenlogo" class="mx-auto mb-4 h-16 w-auto" loading="lazy" />

      <h1 class="text-2xl font-semibold text-center mb-6" style="color: #3EAAB8">
        AlphaRequest
      </h1>

      <p
        v-if="errorMessage"
        role="alert"
        class="mb-6 rounded-md border border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-900/20
               px-4 py-3 text-sm text-red-800 dark:text-red-200"
      >
        {{ errorMessage }}
      </p>

      <p class="text-center text-sm text-gray-600 dark:text-gray-300 mb-6">
        Bitte melden Sie sich mit Ihrem Microsoft-Konto an...
      </p>

      <button
        @click="startAuth"
        :disabled="redirecting"
        class="block text-center w-full text-white font-medium py-2 rounded-md transition disabled:opacity-60"
        style="background-color: #3EAAB8"
        onmouseover="this.style.backgroundColor='#2B7D89'"
        onmouseout="this.style.backgroundColor='#3EAAB8'"
      >
        {{ redirecting ? 'Weiterleitung zu Microsoft…' : 'Mit Microsoft anmelden' }}
      </button>

      <p class="text-center text-xs text-gray-500 dark:text-gray-400 mt-6">
        © AlphaConsult Gruppe
      </p>
    </main>
  </div>
</template>
