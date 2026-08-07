/**
 * ISO-8601-Dauern – Spiegel von backend/services/iso_duration.py.
 * Unterstützt W/D/H/M/S (KEINE Monate/Jahre – variable Länge).
 */

const RE = /^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/
const MULT = [604800, 86400, 3600, 60, 1]

/** Sekunden oder null, wenn ungültig (Backend wirft hier – wir zeigen einen Fehler). */
export function parseDuration(text: string): number | null {
  if (!text || typeof text !== 'string') return null
  const m = RE.exec(text.trim())
  if (!m) return null
  const parts = m.slice(1)
  if (!parts.some((p) => p !== undefined)) return null
  return parts.reduce((sum, p, i) => sum + (p ? parseInt(p, 10) * MULT[i] : 0), 0)
}

/** Serverseitig gültig = parsebar UND > 0. */
export function isValidDuration(text: string): boolean {
  const s = parseDuration(text)
  return s !== null && s > 0
}

/** Sekunden → kompakte ISO-Dauer (z.B. 604800 → 'P1W'). */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  let rest = Math.floor(seconds)
  const d = Math.floor(rest / 86400); rest -= d * 86400
  const h = Math.floor(rest / 3600); rest -= h * 3600
  const min = Math.floor(rest / 60); rest -= min * 60
  const datePart = d ? `${d}D` : ''
  const timePart = [h ? `${h}H` : '', min ? `${min}M` : '', rest ? `${rest}S` : ''].join('')
  if (!datePart && !timePart) return ''
  return `P${datePart}${timePart ? 'T' + timePart : ''}`
}

/** Menschenlesbar für die Oberfläche („7 Tage", „12 Stunden"). */
export function humanDuration(text: string): string {
  const s = parseDuration(text)
  if (s === null || s <= 0) return '—'
  const units: [number, string, string][] = [
    [86400, 'Tag', 'Tage'], [3600, 'Stunde', 'Stunden'],
    [60, 'Minute', 'Minuten'], [1, 'Sekunde', 'Sekunden'],
  ]
  const out: string[] = []
  let rest = s
  for (const [size, one, many] of units) {
    const n = Math.floor(rest / size)
    if (n > 0) { out.push(`${n} ${n === 1 ? one : many}`); rest -= n * size }
  }
  return out.slice(0, 2).join(' ')
}
