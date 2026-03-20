import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User, Permission, TicketType } from '@/types/ticket'

export const useAuthStore = defineStore('auth', () => {
  const user    = ref<User | null>(null)
  const loading = ref(false)

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

  return {
    user, loading,
    isLoggedIn, permissions, hasPermission,
    canView, canManage, isAdmin,
    canCreateTicket, allowedTicketTypes,
    fetchMe, refreshSession, logout,
  }
})