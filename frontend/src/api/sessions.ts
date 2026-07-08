import { client } from './client'

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
  list: () => client.get<{ data: { sessions: ActiveSession[] } }>('/admin/sessions'),
  revokeSession: (sid: string) => client.delete(`/admin/sessions/${encodeURIComponent(sid)}`),
  revokeUser: (userId: string) => client.delete(`/admin/sessions/user/${encodeURIComponent(userId)}`),
  logoutOthers: () => client.post('/admin/sessions/logout-others'),
}
