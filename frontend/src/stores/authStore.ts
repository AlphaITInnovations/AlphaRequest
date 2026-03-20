import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User } from '@/types/ticket'

export const useAuthStore = defineStore('auth', () => {
  const user    = ref<User | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => user.value !== null)
  const isAdmin    = computed(() => user.value?.is_admin ?? false)

  async function fetchMe() {
    loading.value = true
    try {
      const { data } = await authApi.me()
      user.value = data.data
    } catch {
      // 401 = nicht eingeloggt, kein Fehler
      user.value = null
    } finally {
      loading.value = false
    }
  }

  function logout() {
    user.value = null
    window.location.href = '/logout'  // Proxy → Backend löscht Session
  }

  return { user, loading, isLoggedIn, isAdmin, fetchMe, logout }
})