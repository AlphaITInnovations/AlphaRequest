import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import { errorCode, errorMessage } from '@/lib/processErrors'
import type { User, Permission } from '@/types/api'

/** Gate-Codes des Backends (core/dependencies.enforce_employee_link): angemeldet,
 *  aber ohne verknüpften Directus-Mitarbeiter-Datensatz bzw. Directus nicht
 *  erreichbar. KEIN „nicht angemeldet" (das ist 401) – deshalb nicht zum Login,
 *  sondern eine eigene Erklärseite. */
const GATE_CODES = ['NO_DIRECTUS_RECORD', 'DIRECTUS_UNAVAILABLE']

export const useAuthStore = defineStore('auth', () => {
  const user    = ref<User | null>(null)
  const loading = ref(false)
  const sessionExpired   = ref(false)
  const reauthenticating = ref(false)
  const hadSession       = ref(false)
  /** Angemeldet, aber vom Backend-Gate blockiert (kein Directus-Datensatz /
   *  Directus down). Trägt Code + Meldung für die „Kein Zugang"-Seite. */
  const accessDenied = ref<{ code: string; message: string } | null>(null)

  // ── Basis ────────────────────────────────────────────────────────────────────

  const isLoggedIn = computed(() => user.value !== null)

  const permissions = computed<Permission[]>(() => user.value?.permissions ?? [])

  function hasPermission(perm: Permission): boolean {
    return permissions.value.includes(perm)
  }

  // ── Rollen-Shortcuts ──────────────────────────────────────────────────────────

  const canView   = computed(() => hasPermission('view'))
  const canManage = computed(() => hasPermission('manage'))
  const isAdmin   = computed(() => hasPermission('admin'))

  // ── API ───────────────────────────────────────────────────────────────────────

  async function fetchMe() {
    loading.value = true
    try {
      const { data } = await authApi.me()
      user.value = data.data
      accessDenied.value = null
      hadSession.value = true
    } catch (e) {
      user.value = null
      // Angemeldet, aber vom Gate blockiert → Grund festhalten (statt still auf
      // Login zu leiten, was zur Endlosschleife führte).
      const code = errorCode(e)
      accessDenied.value = code && GATE_CODES.includes(code)
        ? { code, message: errorMessage(e, 'Kein Zugang.') }
        : null
    } finally {
      loading.value = false
    }
  }

  async function refreshSession() {
    try {
      const { data } = await authApi.refreshSession()
      user.value = data.data
    } catch {
      // Session abgelaufen → Interceptor leitet auf /login weiter
    }
  }

  function logout() {
    user.value = null
    accessDenied.value = null
    window.location.href = '/logout'
  }

  function markSessionExpired() {
    user.value = null
    sessionExpired.value = true
  }

  /**
   * Öffnet den Microsoft-Login in einem Popup.
   * Nach erfolgreichem Login wird die Session wiederhergestellt
   * und das Modal geschlossen – die Seite bleibt erhalten.
   */
  async function reloginViaPopup(): Promise<boolean> {
    reauthenticating.value = true

    const width = 500
    const height = 650
    const left = window.screenX + (window.innerWidth - width) / 2
    const top = window.screenY + (window.innerHeight - height) / 2

    const popup = window.open(
      '/start-auth',
      'relogin',
      `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no`
    )

    if (!popup) {
      reauthenticating.value = false
      // Popup-Blocker → Fallback auf harten Redirect
      window.location.href = '/login'
      return false
    }

    // Warte bis das Popup geschlossen wird (OAuth Redirect fertig)
    return new Promise<boolean>((resolve) => {
      const timer = setInterval(async () => {
        if (popup.closed) {
          clearInterval(timer)
          // Prüfe ob die Session wieder aktiv ist
          try {
            const { data } = await authApi.me()
            user.value = data.data
            accessDenied.value = null
            sessionExpired.value = false
            reauthenticating.value = false
            resolve(true)
          } catch {
            reauthenticating.value = false
            resolve(false)
          }
        }
      }, 500)
    })
  }

  return {
    user, loading, sessionExpired, reauthenticating, hadSession, accessDenied,
    isLoggedIn, permissions, hasPermission,
    canView, canManage, isAdmin,
    fetchMe, refreshSession, logout, markSessionExpired, reloginViaPopup,
  }
})