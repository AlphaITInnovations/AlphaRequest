import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'

export const client = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

export function setupInterceptors(router: import('vue-router').Router) {
  client.interceptors.response.use(
    res => res,
    err => {
      const status = err.response?.status
      if (status === 401 || status === 403) {
        if (router.currentRoute.value.path !== '/login') {
          const auth = useAuthStore()
          auth.markSessionExpired()
        }
      }
      return Promise.reject(err)
    }
  )
}

/** Gibt true zurück wenn das Backend erreichbar ist */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await axios.get('/api/v1/health', {
      withCredentials: true,
      timeout: 3000,
    })
    return res.status === 200
  } catch {
    return false
  }
}