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
      const url = err.config?.url ?? ''

      // Auth-Endpoints nie abfangen – fetchMe/Router-Guard handeln das
      const isAuthEndpoint = url.includes('/auth/')

      // NUR 401 = Session abgelaufen. 403 ist „keine Berechtigung" (z.B. ein
      // Nicht-Admin ruft einen Admin-Endpoint) und darf NICHT ausloggen –
      // das Aufrufende behandelt den Fehler selbst.
      if (status === 401 && !isAuthEndpoint) {
        if (router.currentRoute.value.path !== '/login') {
          const auth = useAuthStore()
          // Nur Modal zeigen wenn der User GERADE eingeloggt ist
          // (d.h. ein normaler API-Call ist fehlgeschlagen)
          if (auth.isLoggedIn) {
            auth.markSessionExpired()
          }
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