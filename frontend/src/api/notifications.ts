/**
 * In-App-Benachrichtigungen (Glocke). Ergänzung zur Mail – der Server leitet sie
 * aus dem Verlauf der eigenen Aufträge ab (backend/services/process_notifications).
 */
import { client, BACKGROUND_POLL_HEADERS } from '@/api/client'

export type NotificationKind = 'task' | 'progress' | 'addendum' | 'watch' | (string & {})

export interface AppNotification {
  id: number
  ticket_id: number | null
  kind: NotificationKind
  title: string
  body: string | null
  link: string | null
  actor_name: string | null
  created_at: string | null
  read_at: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unread: number
  has_more: boolean
}

export async function listNotifications(params: { before?: number; limit?: number } = {}): Promise<NotificationList> {
  const { data } = await client.get('/notifications', { params })
  return data.data
}

/** `background` = automatische Abfrage (verlängert die Session nicht). */
export async function unreadNotificationCount(background = true): Promise<number> {
  const { data } = await client.get('/notifications/unread-count',
    background ? { headers: BACKGROUND_POLL_HEADERS } : undefined)
  return data.data.unread
}

export async function markNotificationRead(id: number): Promise<number> {
  const { data } = await client.post(`/notifications/${id}:read`)
  return data.data.unread
}

/** `upToId` = neuester GESEHENER Eintrag – Neueres bleibt ungelesen. Gibt die
 *  verbleibende Ungelesen-Zahl zurück. */
export async function markAllNotificationsRead(upToId?: number): Promise<number> {
  const { data } = await client.post('/notifications:read-all', upToId ? { up_to_id: upToId } : {})
  return data.data.unread
}
