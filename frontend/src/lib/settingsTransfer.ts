/**
 * Kleine Helfer für Export/Import von Settings-Listen (Firmen, Fachabteilungen)
 * als JSON – rein clientseitig: Export serialisiert die geladene Liste zum
 * Download, Import liest eine Datei in den Editor; gespeichert (und damit
 * serverseitig validiert) wird über den bestehenden „Speichern"-Pfad des Panels.
 */

/** Daten als hübsch formatierte JSON-Datei herunterladen. */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Ausgewählte Datei als Text lesen und als JSON parsen (wirft bei ungültigem JSON). */
export async function readJsonFile(file: File): Promise<unknown> {
  return JSON.parse(await file.text())
}

/** Datumsstempel für Export-Dateinamen (YYYY-MM-DD). */
export function dateStamp(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * Die Liste aus einem Export-Objekt ziehen: akzeptiert ein Hüllobjekt
 * (`{ kind, <key>: [...] }`) ODER ein nacktes Array. Trägt die Datei einen
 * `kind`, der nicht passt, wird abgebrochen – so landet keine Fachabteilungs-
 * Datei im Firmen-Import (und umgekehrt).
 */
export function extractList(parsed: unknown, key: string, expectedKind: string): unknown[] {
  if (Array.isArray(parsed)) return parsed
  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>
    if (obj.kind && obj.kind !== expectedKind) {
      throw new Error(`Falscher Dateityp: „${String(obj.kind)}“ (erwartet „${expectedKind}“).`)
    }
    if (Array.isArray(obj[key])) return obj[key] as unknown[]
  }
  throw new Error('Die Datei enthält keine gültige Liste.')
}
