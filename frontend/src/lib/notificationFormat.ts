/**
 * Darstellung der In-App-Benachrichtigungen (rein, ohne Vue – testbar ohne DOM).
 */
import type { NotificationKind } from '@/api/notifications'

/** Zahl an der Glocke: ab 100 „99+", damit die Plakette nicht ausufert. */
export function badgeText(n: number): string {
  return n > 99 ? '99+' : String(Math.max(0, Math.floor(n)))
}

/** Barrierefreie Beschriftung des Glocken-Knopfs. */
export function bellLabel(unread: number): string {
  if (unread <= 0) return 'Benachrichtigungen'
  return `Benachrichtigungen (${unread} ungelesen)`
}

const KIND_META: Record<string, { label: string; dot: string }> = {
  task:     { label: 'Neue Aufgabe', dot: 'bg-[#3EAAB8]' },
  progress: { label: 'Fortschritt',  dot: 'bg-gray-400' },
  addendum: { label: 'Nachtrag',     dot: 'bg-violet-500' },
  watch:    { label: 'Beobachtung',  dot: 'bg-green-500' },
}

export function kindMeta(kind: NotificationKind): { label: string; dot: string } {
  return KIND_META[kind] ?? { label: 'Hinweis', dot: 'bg-gray-400' }
}
