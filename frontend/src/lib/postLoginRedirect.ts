/**
 * Ziel-Seite über den Microsoft-Login hinweg merken.
 *
 * Fall: Ein Link aus einer Mail (z. B. `/prozess-auftraege/42?ansicht=bearbeiten`)
 * trifft auf eine abgelaufene Session. Der Router-Guard schickt zum Login, und der
 * OAuth-Rücksprung landet immer auf der Frontend-Startseite – ohne Merken stünde
 * man danach auf der Übersicht statt im Auftrag.
 *
 * Gespeichert wird im `sessionStorage` (pro Tab, überlebt den Rundweg zu
 * Microsoft im selben Tab). Bewusst NICHT als Server-Parameter: so entsteht keine
 * offene Weiterleitung. Beim Einlösen wird nur ein frischer, interner Pfad
 * akzeptiert.
 *
 * Reines Modul (ohne Vue); `storage` ist austauschbar, damit es ohne DOM testbar ist.
 */

const KEY = 'postLoginPath'
/** Älter als das gilt ein gemerktes Ziel als vergessen (abgebrochener Login). */
export const POST_LOGIN_MAX_AGE_MS = 15 * 60_000

type MiniStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

/** Seiten, auf die nach dem Login NICHT zurückgesprungen wird. */
const NICHT_MERKEN = ['/login', '/logout', '/start-auth', '/auth', '/backend-down', '/kein-zugang']

function defaultStorage(): MiniStorage | null {
  try {
    return typeof sessionStorage !== 'undefined' ? sessionStorage : null
  } catch {
    return null   // z. B. gesperrter Speicher
  }
}

/** Nur interne SPA-Pfade: beginnt mit „/", aber kein „//" bzw. „/\" (Protokoll-
 *  relative Fremd-URL) und keine Login-/Fehler-Seite. */
export function isSafeInternalPath(p: unknown): p is string {
  if (typeof p !== 'string' || !p.startsWith('/') || p.length > 2048) return false
  if (p.startsWith('//') || p.startsWith('/\\')) return false
  const pfad = p.split(/[?#]/)[0]
  return !NICHT_MERKEN.some((x) => pfad === x || pfad.startsWith(`${x}/`))
}

export function rememberPostLoginPath(
  path: string, now: number = Date.now(), storage: MiniStorage | null = defaultStorage(),
): void {
  if (!storage || !isSafeInternalPath(path)) return
  try {
    storage.setItem(KEY, JSON.stringify({ path, at: now }))
  } catch { /* Speicher voll/gesperrt – dann eben ohne Rücksprung */ }
}

/** Gemerktes Ziel holen UND entfernen (einmalig). null, wenn nichts Gültiges da ist. */
export function takePostLoginPath(
  now: number = Date.now(), storage: MiniStorage | null = defaultStorage(),
): string | null {
  if (!storage) return null
  let raw: string | null = null
  try {
    raw = storage.getItem(KEY)
    storage.removeItem(KEY)
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const { path, at } = JSON.parse(raw) as { path?: unknown; at?: unknown }
    if (typeof at !== 'number' || now - at > POST_LOGIN_MAX_AGE_MS || now < at) return null
    return isSafeInternalPath(path) ? path : null
  } catch {
    return null
  }
}
