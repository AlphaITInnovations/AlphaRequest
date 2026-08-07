/**
 * Lokales Verzeichnis bekannter Prozess-Schlüssel (localStorage).
 *
 * WARUM ES DAS GIBT: Das Backend bietet KEINE Route, die unveröffentlichte
 * Prozesse auflistet – `GET /processes` liefert ausschließlich den
 * veröffentlichten Katalog, und `GET /processes/{key}/versions` setzt voraus,
 * dass man den Schlüssel bereits kennt. Ein frisch angelegter Entwurf wäre in
 * der Übersicht damit unsichtbar und praktisch verloren.
 *
 * Deshalb merkt sich dieser Browser jeden Schlüssel, den er selbst erzeugt hat
 * (anlegen / importieren / kopieren). Die Übersicht lädt für diese Schlüssel
 * zusätzlich die Versionsliste nach.
 *
 * EINSCHRÄNKUNG: Das ist reine Browser-Kosmetik – an einem anderen Gerät sind
 * fremde Entwürfe weiterhin unsichtbar. Sobald das Backend eine Route zum
 * Auflisten aller Prozesse (inkl. Entwürfe) anbietet, gehört dieses Modul
 * ersatzlos entfernt.
 */

const STORAGE_KEY = 'arm.processKeys'

/** Liest die Liste defensiv – defekter oder gesperrter Speicher darf nie werfen. */
function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((k): k is string => typeof k === 'string' && k.length > 0)
  } catch {
    // Kaputtes JSON, Privatmodus oder gesperrter Speicher → einfach leer.
    return []
  }
}

function write(keys: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  } catch {
    // Speicher nicht verfügbar/voll – kein Grund, die Oberfläche zu stören.
  }
}

/** Alle lokal gemerkten Schlüssel (dedupliziert, stabile Reihenfolge). */
export function loadKnownKeys(): string[] {
  return Array.from(new Set(read()))
}

/** Schlüssel merken (idempotent). */
export function rememberKey(key: string): void {
  if (!key) return
  const keys = loadKnownKeys()
  if (keys.includes(key)) return
  keys.push(key)
  write(keys)
}

/** Schlüssel vergessen – z. B. wenn die letzte Version gelöscht wurde. */
export function forgetKey(key: string): void {
  if (!key) return
  const keys = loadKnownKeys()
  const next = keys.filter((k) => k !== key)
  if (next.length !== keys.length) write(next)
}
