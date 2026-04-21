import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User, Permission, TicketType } from '@/types/ticket'

export const useAuthStore = defineStore('auth', () => {
  const user    = ref<User | null>(null)
  const loading = ref(false)
  const sessionExpired   = ref(false)
  const reauthenticating = ref(false)
  const hadSession       = ref(false)

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

  // ── Ticket-Erstellung ─────────────────────────────────────────────────────────

  function canCreateTicket(type: TicketType): boolean {
    return hasPermission(`create_${type}`)
  }

  const allowedTicketTypes = computed<TicketType[]>(() =>
    permissions.value
      .filter(p => p.startsWith('create_'))
      .map(p => p.replace('create_', '') as TicketType)
  )

  // ── API ───────────────────────────────────────────────────────────────────────

  async function fetchMe() {
    loading.value = true
    try {
      const { data } = await authApi.me()
      user.value = data.data
      hadSession.value = true
    } catch {
      user.value = null
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
    user, loading, sessionExpired, reauthenticating, hadSession,
    isLoggedIn, permissions, hasPermission,
    canView, canManage, isAdmin,
    canCreateTicket, allowedTicketTypes,
    fetchMe, refreshSession, logout, markSessionExpired, reloginViaPopup,
  }
})