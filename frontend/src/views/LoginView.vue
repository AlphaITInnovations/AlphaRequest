<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const logoUrl = '/static/logo.png'
const route = useRoute()
const redirecting = ref(false)

/** Fehlercodes, mit denen der Backend-Callback nach /login?error=… zurückleitet.
 *  Ohne Anzeige wirkte der Login-Knopf so, als würde „nichts passieren". */
const ERROR_MESSAGES: Record<string, string> = {
  token_error: 'Die Anmeldung bei Microsoft konnte nicht abgeschlossen werden (kein Token erhalten). Bitte erneut versuchen.',
  login_failed: 'Beim Login ist ein Fehler aufgetreten. Bitte erneut versuchen – wenden Sie sich an die Administration, falls es weiterhin auftritt.',
  session_expired: 'Ihre Sitzung wurde beendet. Bitte melden Sie sich erneut an.',
  maintenance: 'Während der Wartung können sich nur Administratoren anmelden. Bitte später erneut versuchen.',
}

const errorMessage = computed(() => {
  const code = route.query.error
  if (typeof code !== 'string' || !code) return null
  // Bei Wartung übernimmt der Wartungs-Hinweis die Erklärung – keine doppelte Meldung.
  if (code === 'maintenance') return null
  return ERROR_MESSAGES[code] || 'Anmeldung fehlgeschlagen. Bitte erneut versuchen.'
})

// ── Wartungsmodus (öffentlicher Status) ──────────────────────────────────────
interface Maintenance { active: boolean; message: string | null; planned_end: string | null; since: string | null }
const maintenance = ref<Maintenance | null>(null)
// Der Login wurde gerade wegen Wartung abgewiesen (Rücksprung mit ?error=maintenance).
const blockedByMaintenance = computed(() => route.query.error === 'maintenance')

/** „2026-10-14T18:30" → „14.10.2026, 18:30 Uhr". Nicht parsebares unverändert zeigen. */
function formatEnd(raw: string | null): string | null {
  if (!raw) return null
  const d = new Date(raw)
  if (isNaN(d.getTime())) return raw
  return d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) + ' Uhr'
}
const plannedEnd = computed(() => formatEnd(maintenance.value?.planned_end ?? null))

onMounted(async () => {
  try {
    const res = await axios.get('/api/v1/maintenance', { timeout: 4000 })
    maintenance.value = res.data
  } catch {
    // Status nicht ladbar → kein Hinweis (der Login bleibt normal nutzbar).
    maintenance.value = null
  }
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

      <!-- Wartungsmodus: Hinweis + geplantes Ende. Nur Admins können sich während
           der Wartung anmelden. -->
      <div
        v-if="maintenance?.active"
        role="status"
        class="mb-6 rounded-md border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-900/20
               px-4 py-3 text-sm text-amber-900 dark:text-amber-100"
      >
        <p class="flex items-center gap-2 font-semibold">
          <span>🛠️</span><span>Wartungsmodus</span>
        </p>
        <p class="mt-1">
          Die Anwendung wird gerade gewartet. In dieser Zeit können sich nur
          Administrator:innen anmelden.
        </p>
        <p v-if="maintenance.message" class="mt-2 whitespace-pre-line">{{ maintenance.message }}</p>
        <p v-if="plannedEnd" class="mt-2">
          <span class="font-medium">Voraussichtlich bis:</span> {{ plannedEnd }}
        </p>
        <p v-if="blockedByMaintenance" class="mt-2 text-xs text-amber-800/80 dark:text-amber-200/70">
          Ihre Anmeldung wurde währenddessen nicht zugelassen.
        </p>
      </div>

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
