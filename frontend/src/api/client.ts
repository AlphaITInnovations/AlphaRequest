import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'
import { createWatchers } from '@/composables/createWatchers'

export const client = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Beim Erstellen die im Create-Flow (TicketCreateView) gesammelten Beobachter
// mitschicken. Bewusst eng begrenzt: nur die beiden Create-Endpunkte und nur,
// wenn eine Beobachter-Liste gesetzt ist. So müssen die 9 Ticket-Composables
// nicht einzeln angepasst werden. Die Liste wird bei jedem Create-Mount via
// resetCreateWatchers() neu gesetzt.
client.interceptors.request.use(config => {
  const url = config.url ?? ''
  const isCreate = (config.method ?? '').toLowerCase() === 'post'
    && (url === '/tickets' || url === '/tickets/basis')
  if (isCreate && createWatchers.value.length && config.data && typeof config.data === 'object') {
    config.data = { ...config.data, watchers: createWatchers.value }
  }
  return config
})

export function setupInterceptors(router: import('vue-router').Router) {
  client.interceptors.response.use(
    res => res,
    err => {
      const status = err.response?.status
      const url = err.config?.url ?? ''

      // Auth-Endpoints nie abfangen – fetchMe/Router-Guard handeln das
      const isAuthEndpoint = url.includes('/auth/')

      if ((status === 401 || status === 403) && !isAuthEndpoint) {
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