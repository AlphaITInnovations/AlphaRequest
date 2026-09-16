<script setup lang="ts">
/**
 * Verlauf eines Prozess-Auftrags.
 *
 * Der Server liefert den Verlauf schon redigiert (nicht sichtbare Felder und
 * fremde interne Nachträge fehlen) – hier wird NICHT nach Rechten gefiltert. Was
 * ankommt, darf gezeigt werden.
 *
 * Darstellung: eine kompakte Zeitachse mit Symbol-Punkten je Ereignisart. Ein
 * „Angaben geändert"-Eintrag zeigt NUR die Anzahl im Titel und die betroffenen
 * Felder als (aufklappbare) Chips – so bleibt der Überblick, auch wenn viele
 * Felder auf einmal geändert wurden. Feld-WERTE stehen bewusst nicht im Verlauf
 * (Feld-Sicht, siehe services/process_events.py).
 *
 * NACHTRÄGE RUHEN – NUR IN DER OBERFLÄCHE
 * ---------------------------------------
 * Die Nachtrags-Eingabe und die Nachtrags-EINTRÄGE (`action='comment'`) werden
 * derzeit nicht gezeigt. Das ist eine reine Anzeige-Entscheidung: Tabelle,
 * Endpunkte (`api/processEvents.addComment`) und der Verlauf selbst bleiben
 * unverändert, ältere Nachträge stehen weiter in der Datenbank. Zurückholen
 * heißt: den Filter unten entfernen und die Eingabe wieder einsetzen (die
 * Rechte-Angaben `canComment`/`canBeInternal` sind dafür absichtlich noch da).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { listEvents, type ProcessEvent } from '@/api/processEvents'
import {
  absoluteTime, eventFields, eventIcon, eventTitle, eventTone, relativeTime,
} from '@/lib/processEventLabels'
import { EMPTY_TEXT, fieldValueText, isEmptyValue } from '@/lib/processFieldFormat'
import type { FieldDef, OptionSources } from '@/types/process'
import { errorMessage } from '@/lib/processErrors'

const props = withDefaults(defineProps<{
  ticketId: number
  /** Feld-Schlüssel → Beschriftung (aus der gepinnten Definition). */
  fieldLabels?: Record<string, string>
  phaseLabels?: Record<string, string>
  groupName?: (id: string) => string
  /** Nutzer-ID → Anzeigename (Beobachter:innen im Verlauf). */
  userName?: (id: string) => string
  /** Feld-Katalog + Stammdaten: nötig, um bei „Angaben geändert" die alt→neu-Werte
   *  lesbar zu machen (Optionen/Namen/Directus-Labels wie in der Leseansicht). */
  fields?: FieldDef[]
  sources?: OptionSources
  /** Ruht mit der Nachtrags-Eingabe (siehe Docstring) – bleibt für die Rückkehr. */
  canComment?: boolean
  canBeInternal?: boolean
  /** Entry-Modus für die Feld-Sicht des Verlaufs (wie beim Detail-GET). `admin`
   *  löst den vollen Admin-Blick – der Verlauf wird nur in der Admin-Ansicht gezeigt. */
  view?: string
}>(), { canComment: true, canBeInternal: false })

const items = ref<ProcessEvent[]>([])
const loading = ref(false)
const fehler = ref<string | null>(null)
/** Nur den Anfang zeigen, bis „alles anzeigen" geklickt wird. */
const alleZeigen = ref(false)
const KURZ = 8
/** Ab wie vielen Feld-Chips ein „updated"-Eintrag eingeklappt wird. */
const CHIPS_KURZ = 6

const ctx = computed(() => ({
  fieldLabels: props.fieldLabels,
  phaseLabels: props.phaseLabels,
  groupName: props.groupName,
  userName: props.userName,
}))

const fieldByKey = computed<Record<string, FieldDef>>(() => {
  const out: Record<string, FieldDef> = {}
  for (const f of props.fields ?? []) out[f.key] = f
  return out
})

/**
 * Neueste zuerst – der Server liefert chronologisch aufsteigend.
 *
 * Nachträge (`action='comment'`) bleiben aus der ANZEIGE: nur die Oberfläche
 * ruht, geladen und gespeichert wird weiter alles (siehe Docstring). Gefiltert
 * wird erst hier und nicht beim Laden, damit `mehrereEpochen` und ein späteres
 * Wiedereinschalten den vollen Verlauf sehen.
 */
const sortiert = computed(() =>
  [...items.value].reverse().filter((e) => e.action !== 'comment'))
const sichtbar = computed(() =>
  alleZeigen.value ? sortiert.value : sortiert.value.slice(0, KURZ))

// Symbol-Punkt je Ton: farbiger Kreis mit weißem Symbol – schneller zu scannen
// als eine reine Textliste.
const TONE_BADGE: Record<string, string> = {
  neutral: 'bg-gray-400 dark:bg-gray-500',
  progress: 'bg-[#3EAAB8]',
  warn: 'bg-amber-500',
  danger: 'bg-red-500',
  comment: 'bg-violet-500',
}

// Einfache Outline-Symbole (stroke=currentColor). Mehrteilige Pfade sind zu einem
// `d` verkettet (Eye: Kontur + Pupille).
const ICON_PATH: Record<string, string> = {
  created: 'M12 4.5v15m7.5-7.5h-15',
  edit: 'M16.862 4.487l1.688-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 '
      + '01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.862 4.487z',
  advance: 'M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3',
  check: 'M4.5 12.75l6 6 9-13.5',
  reject: 'M6 18L18 6M6 6l12 12',
  reopen: 'M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3',
  comment: 'M7.5 8.25h9m-9 3.75h5.25M21 12c0 4.556-4.03 8.25-9 8.25a9.76 9.76 0 '
         + '01-2.555-.337A5.97 5.97 0 015.41 20.97a5.97 5.97 0 01-.474-.065 4.48 4.48 0 '
         + '00.978-2.025.75.75 0 00-.117-.55A8.22 8.22 0 013 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z',
  skip: 'M3 4.5l7.5 7.5-7.5 7.5m9-15l7.5 7.5-7.5 7.5',
  watcher: 'M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 '
         + '3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 '
         + '0-8.573-3.007-9.963-7.178zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
  automation: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z',
  priority: 'M3 3v18M3 4.5h13.5l-3 4.5 3 4.5H3',
  warn: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 '
      + '1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
  dot: 'M12 9.75a2.25 2.25 0 100 4.5 2.25 2.25 0 000-4.5z',
}
const iconPath = (ev: ProcessEvent) => ICON_PATH[eventIcon(ev)] || ICON_PATH.dot

/** Läufe zählen: nach einer Wiederaufnahme beginnt ein neuer Durchlauf. */
const mehrereEpochen = computed(() => new Set(items.value.map((e) => e.epoch)).size > 1)

const phaseName = (ev: ProcessEvent) =>
  ev.phase_key ? (props.phaseLabels?.[ev.phase_key] || ev.phase_key) : null

// „Angaben geändert" je Eintrag einzeln auf-/zuklappen.
const offeneFelder = ref<Set<number>>(new Set())
function toggleFelder(id: number) {
  const next = new Set(offeneFelder.value)
  next.has(id) ? next.delete(id) : next.add(id)
  offeneFelder.value = next
}
const hiddenCount = (ev: ProcessEvent) => Number(ev.details?.fields_hidden) || 0

/** Hat der Eintrag alt→neu-Werte (neue Einträge) oder nur Feld-Schlüssel (alt)? */
function hasChanges(ev: ProcessEvent): boolean {
  const c = ev.details?.changes
  return !!c && typeof c === 'object' && Object.keys(c).length > 0
}

interface ChangeRow { key: string; label: string; from: string; to: string; fromEmpty: boolean; complex: boolean }

/** Eine Zeile je geändertem Feld: Beschriftung + alt→neu, lesbar formatiert
 *  (Optionen/Namen/Directus-Labels wie in der Leseansicht). Wiederholgruppen und
 *  Anhänge zeigen „aktualisiert" statt eines rohen Objekt-Dumps. */
function changeRows(ev: ProcessEvent): ChangeRow[] {
  const keys = Array.isArray(ev.details?.fields)
    ? (ev.details!.fields as unknown[]).filter((k): k is string => typeof k === 'string') : []
  const changes = (ev.details?.changes ?? {}) as Record<string, { from?: unknown; to?: unknown }>
  return keys.map((key) => {
    const field = fieldByKey.value[key]
    const ch = changes[key] ?? {}
    const complex = !!field && (field.widget === 'collection' || field.widget === 'attachment')
    const fmt = (v: unknown) => (field
      ? fieldValueText(field, v, props.sources)
      : (v === null || v === undefined || v === '' ? EMPTY_TEXT : String(v)))
    return {
      key,
      label: props.fieldLabels?.[key] || key,
      from: fmt(ch.from),
      to: fmt(ch.to),
      fromEmpty: isEmptyValue(ch.from),
      complex,
    }
  })
}
function changeInfo(ev: ProcessEvent): { shown: ChangeRow[]; more: number; hidden: number } {
  const rows = changeRows(ev)
  const offen = offeneFelder.value.has(ev.id)
  const shown = offen ? rows : rows.slice(0, CHIPS_KURZ)
  return { shown, more: offen ? 0 : Math.max(0, rows.length - shown.length), hidden: hiddenCount(ev) }
}

/** Fallback für Alt-Einträge OHNE Werte: nur die Feldnamen als Chips. */
function chips(ev: ProcessEvent): { shown: string[]; more: number; hidden: number } {
  const { names, hidden } = eventFields(ev, ctx.value)
  const offen = offeneFelder.value.has(ev.id)
  const shown = offen ? names : names.slice(0, CHIPS_KURZ)
  return { shown, more: offen ? 0 : Math.max(0, names.length - shown.length), hidden }
}

async function load() {
  loading.value = true
  fehler.value = null
  try {
    const res = await listEvents(props.ticketId, { limit: 500, view: props.view })
    items.value = res.items
  } catch (e) {
    fehler.value = errorMessage(e, 'Verlauf konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

/** Von außen nach einer Aktion (Speichern/Weiterschalten) neu laden. */
defineExpose({ reload: load })

onMounted(load)
watch(() => props.ticketId, load)
</script>

<template>
  <div class="card-section">
    <div class="flex items-center justify-between gap-2 mb-3">
      <h3 class="section-title mb-0">Verlauf</h3>
      <button @click="load" :disabled="loading"
              class="text-xs text-gray-400 hover:text-[#3EAAB8] disabled:opacity-40">
        Aktualisieren
      </button>
    </div>

    <!-- Die Nachtrags-Eingabe fehlt ABSICHTLICH: die Nachtrags-Oberfläche ruht
         (siehe Docstring). Endpunkt und Datenbank sind unverändert. -->

    <div v-if="fehler" class="text-sm text-red-600 mb-2">{{ fehler }}</div>
    <div v-else-if="loading && !items.length" class="text-sm text-gray-400">Wird geladen …</div>
    <p v-else-if="!sortiert.length" class="text-sm text-gray-400 italic">
      Noch keine Einträge.
    </p>

    <ol v-else class="relative space-y-1">
      <!-- Durchgehende Zeitachse hinter den Symbol-Punkten -->
      <span class="absolute left-[11px] top-2 bottom-2 w-px bg-gray-200 dark:bg-white/10" />
      <li v-for="ev in sichtbar" :key="ev.id" class="relative flex gap-2.5">
        <!-- Symbol-Punkt -->
        <span class="relative z-10 flex-shrink-0 mt-0.5 w-[23px] h-[23px] rounded-full
                     flex items-center justify-center text-white ring-4 ring-white dark:ring-[#1b2430]"
              :class="TONE_BADGE[eventTone(ev)]">
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path :d="iconPath(ev)" />
          </svg>
        </span>

        <div class="min-w-0 flex-1 pb-2">
          <div class="flex items-baseline gap-x-2 gap-y-0.5 flex-wrap">
            <span class="text-sm text-gray-800 dark:text-gray-100 font-medium leading-snug">
              {{ eventTitle(ev, ctx) }}
            </span>
            <span v-if="ev.internal"
                  class="px-1.5 py-0.5 rounded text-[10px] bg-violet-100 text-violet-700
                         dark:bg-violet-900/30 dark:text-violet-300">intern</span>
            <span v-if="mehrereEpochen"
                  class="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-500
                         dark:bg-white/10 dark:text-gray-400">Durchlauf {{ ev.epoch + 1 }}</span>
          </div>

          <!-- Meta: wer · wann · in welcher Phase -->
          <div class="text-[11px] text-gray-400 flex items-center gap-1.5 flex-wrap leading-tight">
            <span>{{ ev.actor_type === 'system' ? 'System' : (ev.actor_name || '—') }}</span>
            <span>·</span>
            <span :title="absoluteTime(ev.created_at)">{{ relativeTime(ev.created_at) }}</span>
            <template v-if="phaseName(ev)">
              <span>·</span>
              <span class="truncate max-w-[12rem]">{{ phaseName(ev) }}</span>
            </template>
          </div>

          <!-- „Angaben geändert": alt→neu je Feld, lesbar formatiert (aufklappbar).
               Alt-Einträge ohne Werte fallen auf reine Feld-Chips zurück. -->
          <div v-if="ev.action === 'updated' && hasChanges(ev)" class="mt-1.5 space-y-0.5">
            <div v-for="c in changeInfo(ev).shown" :key="c.key" class="text-[12px] leading-snug">
              <span class="text-gray-400">{{ c.label }}:</span>
              <template v-if="c.complex">
                <span class="text-gray-500 dark:text-gray-400"> aktualisiert</span>
              </template>
              <template v-else>
                <template v-if="!c.fromEmpty">
                  <span class="text-gray-400 line-through decoration-gray-300 dark:decoration-white/25">
                    {{ c.from }}</span>
                  <span class="text-gray-300 dark:text-gray-500"> → </span>
                </template>
                <span class="text-gray-800 dark:text-gray-100 font-medium">{{ c.to }}</span>
              </template>
            </div>
            <div class="flex items-center gap-2 pt-0.5">
              <button v-if="changeInfo(ev).more" type="button" @click="toggleFelder(ev.id)"
                      class="text-[11px] text-[#3EAAB8] hover:underline">
                +{{ changeInfo(ev).more }} weitere
              </button>
              <button v-else-if="offeneFelder.has(ev.id) && changeRows(ev).length > CHIPS_KURZ"
                      type="button" @click="toggleFelder(ev.id)"
                      class="text-[11px] text-gray-400 hover:underline">weniger</button>
              <span v-if="changeInfo(ev).hidden" class="text-[11px] text-amber-600 dark:text-amber-400"
                    title="Für Sie nicht sichtbare Felder">
                +{{ changeInfo(ev).hidden }} nicht sichtbar
              </span>
            </div>
          </div>

          <!-- Fallback: Alt-Einträge ohne Wert-Diff → Felder als Chips -->
          <div v-else-if="ev.action === 'updated'" class="mt-1.5 flex flex-wrap items-center gap-1">
            <span v-for="name in chips(ev).shown" :key="name"
                  class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[11px] leading-tight
                         bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300">{{ name }}</span>
            <button v-if="chips(ev).more" type="button" @click="toggleFelder(ev.id)"
                    class="px-1.5 py-0.5 rounded-md text-[11px] text-[#3EAAB8] hover:underline">
              +{{ chips(ev).more }} weitere
            </button>
            <button v-else-if="offeneFelder.has(ev.id) && eventFields(ev, ctx).names.length > CHIPS_KURZ"
                    type="button" @click="toggleFelder(ev.id)"
                    class="px-1.5 py-0.5 rounded-md text-[11px] text-gray-400 hover:underline">
              weniger
            </button>
            <span v-if="chips(ev).hidden"
                  class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[11px] leading-tight
                         text-amber-600 dark:text-amber-400" :title="'Für Sie nicht sichtbare Felder'">
              +{{ chips(ev).hidden }} nicht sichtbar
            </span>
          </div>

          <!-- Freitext eines Ereignisses: Abteilungs-Notiz, Ablehnungs- oder
               Wiederaufnahme-Grund. Nachträge sind hier nicht dabei (ausgefiltert). -->
          <p v-if="ev.body"
             class="mt-1.5 text-sm whitespace-pre-wrap rounded-lg px-3 py-2
                    bg-gray-50 dark:bg-white/[0.04] text-gray-700 dark:text-gray-200">{{ ev.body }}</p>
        </div>
      </li>
    </ol>

    <button v-if="sortiert.length > KURZ" @click="alleZeigen = !alleZeigen"
            class="mt-2 text-xs text-[#3EAAB8] hover:underline">
      {{ alleZeigen ? 'Weniger anzeigen' : `Alle ${sortiert.length} Einträge anzeigen` }}
    </button>
  </div>
</template>
