<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { authApi } from '@/api/auth'

const auth   = useAuthStore()
const router = useRouter()

// ── Popup-Erkennung ──────────────────────────────────────────────────────────
// Wenn diese App in einem Popup geöffnet wurde (nach OAuth-Callback),
// schließen wir das Popup sofort – der Opener pollt auf popup.closed.
if (window.opener && !window.opener.closed) {
  window.close()
}

// ── Session-Heartbeat ────────────────────────────────────────────────────────
// Prüft alle 30s ob die Session noch lebt über /auth/check.
// Dieser Endpoint aktualisiert last_activity NICHT – damit wird
// der Inaktivitäts-Timeout des Backends nicht zurückgesetzt.
let heartbeatTimer: ReturnType<typeof setInterval> | null = null

async function checkSession() {
  if (!auth.isLoggedIn || auth.sessionExpired) return
  if (router.currentRoute.value.path === '/login') return

  try {
    await authApi.checkSession()
    // Session noch gültig – nichts zu tun
  } catch {
    // 401 → Interceptor ruft markSessionExpired() auf
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') {
    // User kommt zurück zum Tab → sofort prüfen
    checkSession()
  }
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = setInterval(checkSession, 10_000)
  document.addEventListener('visibilitychange', onVisibilityChange)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  document.removeEventListener('visibilitychange', onVisibilityChange)
}

onMounted(() => {
  startHeartbeat()
})

onUnmounted(() => {
  stopHeartbeat()
})

// ── Modal-Aktionen ───────────────────────────────────────────────────────────

async function relogin() {
  const success = await auth.reloginViaPopup()
  if (!success) {
    // Modal bleibt offen, User kann es erneut versuchen
  }
}

function goToLogin() {
  auth.sessionExpired = false
  window.location.href = '/login'
}
</script>

<template>
  <RouterView />

  <!-- Session-Expired-Modal -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="auth.sessionExpired"
           class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl border border-gray-200/80
                    dark:border-white/[0.09] max-w-md w-full mx-4 p-8 text-center">

          <!-- Icon -->
          <div class="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full
                      bg-amber-100 dark:bg-amber-900/30">
            <svg class="h-7 w-7 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24"
                 stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round"
                    d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>

          <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            Sitzung abgelaufen
          </h2>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
            Sie wurden aufgrund von Inaktivität automatisch abgemeldet.<br />
            Ihre Eingaben bleiben erhalten – melden Sie sich einfach erneut an.
          </p>

          <!-- Erneut anmelden (Popup) -->
          <button @click="relogin"
                  :disabled="auth.reauthenticating"
                  class="w-full rounded-xl bg-[#3EAAB8] px-5 py-2.5 text-sm font-semibold
                         text-white shadow-sm hover:bg-[#35969F] transition focus:outline-none
                         focus:ring-2 focus:ring-[#3EAAB8]/50
                         disabled:opacity-60 disabled:cursor-not-allowed">
            <span v-if="auth.reauthenticating" class="inline-flex items-center gap-2">
              <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Anmeldung läuft…
            </span>
            <span v-else>Erneut anmelden</span>
          </button>

          <!-- Fallback: Zum Login -->
          <button @click="goToLogin"
                  class="mt-3 w-full rounded-xl border border-gray-200 dark:border-white/10
                         px-5 py-2.5 text-sm font-medium text-gray-600 dark:text-gray-300
                         hover:bg-gray-50 dark:hover:bg-white/5 transition">
            Zur Login-Seite
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>