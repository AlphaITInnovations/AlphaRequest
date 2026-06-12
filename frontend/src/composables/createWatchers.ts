import { ref } from 'vue'
import type { Watcher } from '@/types/ticket'

/**
 * Geteilte Beobachter-Liste für den Erstellungs-Flow.
 *
 * Die TicketCreateView setzt sie beim Mounten (Ersteller vorausgewählt) und
 * stellt sie der „Details"-Sidebar zur Verfügung. Die Create-Composables hängen
 * sie beim Absenden über `withWatchers()` an den Payload — explizit, damit klar
 * ist, dass die Beobachter mitgeschickt werden.
 */
export const createWatchers = ref<Watcher[]>([])

export function resetCreateWatchers(owner?: Watcher | null) {
  createWatchers.value = owner ? [owner] : []
}

export function addCreateWatcher(id: string, name: string) {
  if (!id || createWatchers.value.some(w => w.id === id)) return
  createWatchers.value = [...createWatchers.value, { id, name }]
}

export function removeCreateWatcher(id: string) {
  createWatchers.value = createWatchers.value.filter(w => w.id !== id)
}

/** Hängt die aktuelle Beobachter-Liste an einen Create-Payload an. */
export function withWatchers<T extends Record<string, unknown>>(payload: T): T & { watchers: Watcher[] } {
  return { ...payload, watchers: createWatchers.value }
}
