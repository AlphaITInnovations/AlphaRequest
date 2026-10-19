import axios from 'axios'
import { ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'

export const client = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

/** LIVE-Erreichbarkeit des Backends. Der Router-Guard (main.ts) liest diesen Wert –
 *  deshalb ein reaktiver Ref statt eines beim Start eingefrorenen Flags: sonst
 *  blieb man nach einem kurzen Backend-Ausfall dauerhaft auf „/backend-down"
 *  hängen, weil der Guard den alten (false-)Wert festhielt und jeden Rücksprung
 *  – auch den Retry-Button – wieder dorthin umleitete. */
export const backendReachable = ref(true)

/** Für AUTOMATISCHE Hintergrund-Abfragen (Live-Ansichten): der Server
 *  authentifiziert normal, wertet sie aber NICHT als Nutzer-Aktivität – sonst
 *  hielte ein offener Live-Reiter die Session auf einem unbeaufsichtigten
 *  Rechner ewig am Leben (backend/core/dependencies.BACKGROUND_POLL_HEADER). */
export const BACKGROUND_POLL_HEADERS = { 'X-Background-Poll': '1' } as const

/** Live-Abfragen nur, solange der Tab sichtbar ist (verborgen = niemand schaut hin). */
export function tabVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible'
}

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

/** Gibt true zurück wenn das Backend erreichbar ist. Aktualisiert dabei
 *  `backendReachable`, damit der Router-Guard immer den aktuellen Zustand sieht
 *  (und der Retry auf „/backend-down" nach Rückkehr des Backends greift). */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    // /ping statt /health: ohne die ausgehende Frontend-Probe, die bei Netzproblemen
    // zwischen Backend und Frontend-URL Sekunden hängen kann (→ falsches „down").
    const opts = { withCredentials: true, timeout: 3000, validateStatus: () => true }
    let res = await axios.get('/api/v1/ping', opts)
    // 404 = das Backend ANTWORTET, kennt /ping aber noch nicht (älterer Stand,
    // Rollback, Dev-Backend nicht aktualisiert) → ersatzweise /health, statt alle
    // fälschlich auf „Server nicht erreichbar" zu schicken.
    if (res.status === 404) res = await axios.get('/api/v1/health', opts)
    const ok = res.status === 200
    backendReachable.value = ok
    return ok
  } catch {
    backendReachable.value = false
    return false
  }
}