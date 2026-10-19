/**
 * In-App-Benachrichtigungen (Glocke): Ungelesen-Zahl + Liste.
 *
 * Die Zahl wird im Hintergrund abgefragt – einmal pro Minute, nur bei sichtbarem
 * Tab und als Hintergrund-Abfrage markiert (verlängert die Session NICHT). Beim
 * Zurückkehren in den Tab sofort. Die Liste lädt erst beim Öffnen der Glocke.
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import {
  listNotifications, markAllNotificationsRead, markNotificationRead,
  unreadNotificationCount, type AppNotification,
} from '@/api/notifications'
import { tabVisible } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

const POLL_MS = 60_000

export const useNotificationStore = defineStore('notifications', () => {
  const unread = ref(0)
  const items = ref<AppNotification[]>([])
  const hasMore = ref(false)
  const loading = ref(false)
  const loadError = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  /** Anzahl aktiver Glocken (beim Seitenwechsel kann die neue vor dem Abbau der
   *  alten erscheinen – erst wenn KEINE mehr da ist, wird der Takt gestoppt). */
  let abonnenten = 0
  /** Signal an die geöffnete Auftragsseite: neu laden (Klick auf eine Meldung zum
   *  bereits geöffneten Auftrag – gleiche URL, der Router navigiert nicht). */
  const reloadTick = ref(0)
  /** Zählt lokale Markierungen; ändert er sich während eines Ladevorgangs, ist
   *  dessen Antwort älter als der lokale Stand (siehe loadList). */
  let markEpoch = 0
  const lokalGelesen = new Set<number>()
  let alleGelesenBis: number | null = null

  /** Lokale Markierungen auf (ggf. veraltete) Server-Einträge erneut anwenden. */
  function lokaleMarkierungenAnwenden(list: AppNotification[]): AppNotification[] {
    const jetzt = new Date().toISOString()
    return list.map((n) => (!n.read_at && (lokalGelesen.has(n.id)
      || (alleGelesenBis !== null && n.id <= alleGelesenBis)) ? { ...n, read_at: jetzt } : n))
  }

  function aktiv(): boolean {
    const auth = useAuthStore()
    return auth.isLoggedIn && !auth.sessionExpired
  }

  async function refreshUnread() {
    if (!aktiv()) return
    const epoch = markEpoch
    try {
      const n = await unreadNotificationCount(true)
      if (epoch === markEpoch) unread.value = n   // sonst überholt von einer Markierung
    } catch { /* still: die Zahl ist Beiwerk, beim nächsten Takt erneut */ }
  }

  // Personenwechsel (Abmelden / Neuanmeldung per Popup als andere Person): nichts
  // von der vorherigen Person stehen lassen.
  const auth = useAuthStore()
  watch(() => auth.user?.id ?? null, (neu, alt) => {
    if (neu === alt) return
    items.value = []
    hasMore.value = false
    loadError.value = false
    unread.value = 0
    lokalGelesen.clear()
    alleGelesenBis = null
    if (neu) void refreshUnread()
  })

  async function loadList() {
    if (!aktiv()) return
    loading.value = true
    loadError.value = false
    const epoch = markEpoch
    try {
      const res = await listNotifications({ limit: 20 })
      items.value = lokaleMarkierungenAnwenden(res.items)
      hasMore.value = res.has_more
      // Während des Ladens markiert? Dann ist die Zahl der Antwort veraltet.
      if (epoch === markEpoch) unread.value = res.unread
      else void refreshUnread()
    } catch {
      loadError.value = true
    } finally {
      loading.value = false
    }
  }

  async function loadMore() {
    const last = items.value[items.value.length - 1]
    if (!last || loading.value) return
    loading.value = true
    try {
      const res = await listNotifications({ before: last.id, limit: 20 })
      items.value = [...items.value, ...lokaleMarkierungenAnwenden(res.items)]
      hasMore.value = res.has_more
    } catch {
      loadError.value = true
    } finally {
      loading.value = false
    }
  }

  async function markRead(n: AppNotification) {
    if (n.read_at) return
    markEpoch++
    lokalGelesen.add(n.id)
    n.read_at = new Date().toISOString()          // sofort sichtbar, Server folgt
    unread.value = Math.max(0, unread.value - 1)
    try {
      unread.value = await markNotificationRead(n.id)
    } catch { /* nächster Abruf korrigiert die Zahl */ }
  }

  /** Nur die GESEHENEN (bis zum neuesten geladenen Eintrag) – eine inzwischen
   *  eingetroffene Meldung bleibt ungelesen. */
  async function markAllRead() {
    const bis = items.value[0]?.id
    if (!bis) return
    markEpoch++
    alleGelesenBis = Math.max(alleGelesenBis ?? 0, bis)
    const jetzt = new Date().toISOString()
    for (const n of items.value) if (!n.read_at) n.read_at = jetzt
    unread.value = 0
    try {
      unread.value = await markAllNotificationsRead(bis)
    } catch {
      await refreshUnread()
    }
  }

  function onVisibility() {
    if (tabVisible()) void refreshUnread()
  }

  /** Mehrfaches Starten (z. B. bei jedem Seitenwechsel) legt keinen zweiten Takt
   *  an, frischt aber die Zahl sofort auf. */
  function startPolling() {
    abonnenten++
    void refreshUnread()
    if (timer) return
    timer = setInterval(() => { if (tabVisible()) void refreshUnread() }, POLL_MS)
    document.addEventListener('visibilitychange', onVisibility)
  }

  function stopPolling() {
    abonnenten = Math.max(0, abonnenten - 1)
    if (abonnenten > 0) return
    if (timer) { clearInterval(timer); timer = null }
    document.removeEventListener('visibilitychange', onVisibility)
  }

  return {
    unread, items, hasMore, loading, loadError, reloadTick,
    refreshUnread, loadList, loadMore, markRead, markAllRead, startPolling, stopPolling,
  }
})
