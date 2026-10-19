/**
 * Beantragte Änderungen für die Prüf-/Freigabe-Ansicht (alt → neu je Feld).
 *
 * Grundlage sind die `updated`-Einträge des aktuellen Durchlaufs (epoch) im
 * Verlauf: der Server hält beim Anlegen fest, was von der Vorbelegung abweicht
 * (bei „Meine Stammdaten" = dem Directus-Bestand), und später jede Bearbeitung.
 *
 * Welche Änderung gezeigt wird:
 *  - Wert geändert (alt → neu): immer.
 *  - Wert entfernt (alt → leer): immer, als „entfernt".
 *  - Neu eingetragen (leer → neu): nur bei Feldern MIT Vorbelegung. Dort ist der
 *    Bestand die Vergleichsbasis – ein vorher leeres, jetzt befülltes Feld ist eine
 *    echte beantragte Änderung. Ohne Vorbelegung (z. B. Onboarding) ist „leer → neu"
 *    nur eine Erst-Eingabe und bleibt unmarkiert.
 *
 * Reines Modul (ohne Vue/DOM), damit es ohne jsdom testbar ist.
 */
import type { ProcessEvent } from '@/api/processEvents'
import type { FieldDef, OptionSources } from '@/types/process'
import { fieldValueText, isEmptyValue } from '@/lib/processFieldFormat'

export interface ReviewChange {
  fromText: string
  toText: string
  /** Vorher leer → in der Ansicht nur der neue Wert (mit „neu"-Hinweis). */
  fromEmpty: boolean
  /** Jetzt leer → in der Ansicht „entfernt". */
  toEmpty: boolean
}

/** `updated`-Änderungen EINES Durchlaufs zusammenführen: ältester „from",
 *  jüngster „to" je Feld (Events kommen chronologisch aufsteigend). */
export function mergeEpochChanges(
  events: ProcessEvent[], epoch: number,
): Record<string, { from: unknown; to: unknown }> {
  const merged: Record<string, { from: unknown; to: unknown }> = {}
  for (const ev of events) {
    if (ev.epoch !== epoch || ev.action !== 'updated') continue
    const ch = (ev.details?.changes ?? {}) as Record<string, { from?: unknown; to?: unknown }>
    for (const [k, v] of Object.entries(ch)) {
      if (!(k in merged)) merged[k] = { from: v?.from, to: v?.to }
      else merged[k].to = v?.to
    }
  }
  return merged
}

/** Zusammengeführte Änderungen → anzeigefertige Einträge (siehe Regeln oben). */
export function buildReviewChangeMap(
  merged: Record<string, { from: unknown; to: unknown }>,
  fieldByKey: Record<string, FieldDef>,
  sources?: OptionSources,
): Record<string, ReviewChange> {
  const out: Record<string, ReviewChange> = {}
  for (const [k, v] of Object.entries(merged)) {
    const f = fieldByKey[k]
    if (!f || JSON.stringify(v.from) === JSON.stringify(v.to)) continue
    const fromEmpty = isEmptyValue(v.from)
    const toEmpty = isEmptyValue(v.to)
    if (fromEmpty && toEmpty) continue                 // null ↔ "" ist keine Änderung
    if (fromEmpty && !f.prefill) continue              // reine Erst-Eingabe ohne Bestand
    out[k] = {
      fromText: fieldValueText(f, v.from, sources),
      toText: fieldValueText(f, v.to, sources),
      fromEmpty,
      toEmpty,
    }
  }
  return out
}
