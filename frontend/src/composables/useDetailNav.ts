import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/**
 * Master-Detail-Auswahl über die URL (?…&item=<index>), damit Browser Vor/Zurück
 * zwischen Liste und Detail funktioniert. `count` liefert die aktuelle Listenlänge
 * (für die Gültigkeitsprüfung des Index).
 */
export function useDetailNav(count: () => number) {
  const route = useRoute()
  const router = useRouter()

  const selected = computed<number | null>(() => {
    const it = route.query.item
    if (typeof it !== 'string') return null
    const n = Number(it)
    return Number.isInteger(n) && n >= 0 && n < count() ? n : null
  })

  function open(i: number) {
    router.push({ query: { ...route.query, item: String(i) } })
  }
  function back() {
    const q = { ...route.query }
    delete q.item
    router.push({ query: q })
  }

  return { selected, open, back }
}
