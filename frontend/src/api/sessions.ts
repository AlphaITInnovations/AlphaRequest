import { client, BACKGROUND_POLL_HEADERS } from './client'

export interface ActiveSession {
  sid: string
  user_id: string
  user_name: string | null
  ip: string | null
  user_agent: string | null
  created_at: string
  last_seen: string
  age_seconds: number
  current: boolean
}

export const sessionsApi = {
  /** `background` = automatische Live-Abfrage (verlängert die Session nicht). */
  list: (background = false) => client.get<{ data: { sessions: ActiveSession[] } }>(
    '/admin/sessions', background ? { headers: BACKGROUND_POLL_HEADERS } : undefined),
  revokeSession: (sid: string) => client.delete(`/admin/sessions/${encodeURIComponent(sid)}`),
  revokeUser: (userId: string) => client.delete(`/admin/sessions/user/${encodeURIComponent(userId)}`),
  logoutOthers: () => client.post('/admin/sessions/logout-others'),
}
