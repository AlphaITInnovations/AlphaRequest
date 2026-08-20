<script setup lang="ts">
/**
 * Nur-Lese-Ansicht der Werte eines Prozess-Auftrags.
 *
 * Sichtbarkeit läuft über visibleFieldKeys() – denselben Filter, den der Server
 * beim Ausliefern anwendet. Werden Felder ausgeblendet, weist ein Hinweis am
 * Fuß darauf hin: sonst wirkt eine vertrauliche Angabe schlicht wie „nicht
 * ausgefüllt".
 *
 * Ist eine Phase übergeben, wird deren Layout (Abschnitte, Breiten, Deko)
 * genauso wie im Formular gerendert – die Lese-Ansicht soll wie das Formular
 * aussehen, nur ohne Eingabefelder. Alles, was dabei nicht vorkommt, sammelt der
 * Abschnitt „Weitere Angaben": in der Gesamtansicht darf kein erfasster Wert
 * verloren gehen (auch nicht bei mode='hidden' oder unerfüllter Bedingung).
 */
import { computed } from 'vue'
import type {
  FieldDef, LayoutItem, LayoutSection as LayoutSectionDef, OptionSources, PhaseDef,
  ProcessDefinition, SubField,
} from '@/types/process'
import { colSpanClass, mergedSections, resolveLayout, REST_SECTION_TITLE } from '@/lib/processLayout'
// Die Wertdarstellung liegt in einem reinen Modul, damit die Export-/Druckansicht
// (lib/processPdf.ts) Zeichen für Zeichen dasselbe zeigt wie diese Lese-Ansicht.
import {
  collectionEntries, fieldValueText, isWideWidget, subFieldLabel, subValueText,
} from '@/lib/processFieldFormat'
import { visibleFieldKeys } from '@/lib/processSim'
import type { SimViewer } from '@/lib/processSim'
import LayoutSection from './LayoutSection.vue'
import LayoutDecoration from './LayoutDecoration.vue'
import ReadonlyField from '@/components/ReadonlyField.vue'

const props = defineProps<{
  definition: ProcessDefinition
  values: Record<string, unknown>
  viewer: SimViewer
  sources?: OptionSources
  phase?: PhaseDef | null
}>()

const catalog = computed<FieldDef[]>(() => props.definition?.fields ?? [])
const vals = computed<Record<string, unknown>>(() => props.values ?? {})

const allowed = computed<Set<string>>(() =>
  props.definition ? visibleFieldKeys(props.definition, props.viewer) : new Set<string>())

// ── Abschnitte aufbauen ──────────────────────────────────────────────────────

interface FieldRow { kind: 'field'; key: string; cols: number; f: FieldDef }
interface DecoRow { kind: 'deco'; key: string; cols: number; item: LayoutItem }
type Row = FieldRow | DecoRow
interface Block { section: LayoutSectionDef; rows: Row[] }

function fieldRow(f: FieldDef, cols: number): FieldRow {
  return { kind: 'field', key: `f:${f.key}`, cols: isWideWidget(f.widget) ? 12 : cols, f }
}

function section(title: string, variant: LayoutSectionDef['variant']): LayoutSectionDef {
  return { type: 'section', title, variant, badge: null, description: null,
    collapsed: false, items: [] }
}

/** Abschnitte aus dem Phasen-Layout (leer, wenn keine Phase übergeben wurde). */
const phaseBlocks = computed<Block[]>(() => {
  const p = props.phase
  if (!p || !props.definition) return []
  const byKey = new Map(catalog.value.map((f) => [f.key, f]))
  return resolveLayout(props.definition, p, vals.value, props.viewer)
    .map(({ section: sec, items }) => ({
      section: sec,
      rows: items.flatMap((it, i): Row[] => {
        if (it.rendered) {
          const f = byKey.get(it.rendered.field.key)
          // Zusätzliches Sichtbarkeits-Gate: resolveLayout kennt nur die Phase,
          // der Katalog-Filter entscheidet über vertrauliche Felder.
          return f && allowed.value.has(f.key) ? [fieldRow(f, it.cols)] : []
        }
        // Deko bleibt auch in der Lese-Ansicht: Hinweisboxen erklären die Werte,
        // und ohne sie stünde ein reiner Hinweis-Abschnitt plötzlich leer da.
        return [{ kind: 'deco', key: `d:${i}`, cols: it.cols, item: it.item }]
      }),
    }))
    .filter((b) => b.rows.length > 0)
})

/**
 * Ohne übergebene Phase zeigt die Ansicht den GANZEN Auftrag. Dann werden die
 * Abschnitte aller Phasen zusammengeführt (mergedSections), damit die Angaben
 * gegliedert erscheinen statt als eine durchgehende Liste.
 */
const mergedBlocks = computed<Block[]>(() => {
  const byKey = new Map(catalog.value.map((f) => [f.key, f]))
  return mergedSections(props.definition)
    .map((m) => ({
      section: section(m.title, m.variant),
      rows: m.refs.flatMap((ref): Row[] => {
        const f = byKey.get(ref)
        return f && allowed.value.has(f.key) ? [fieldRow(f, 6)] : []
      }),
    }))
    .filter((b) => b.rows.length > 0)
})

const blocks = computed<Block[]>(() => {
  // Mit Phase: deren Layout. Ohne Phase: Abschnitte über alle Phasen.
  const out = props.phase ? [...phaseBlocks.value] : [...mergedBlocks.value]
  const shown = new Set<string>()
  for (const b of out) for (const r of b.rows) if (r.kind === 'field') shown.add(r.f.key)

  const rest = catalog.value.filter((f) => allowed.value.has(f.key) && !shown.has(f.key))
  if (!rest.length) return out

  const restRows = rest.map((f) => fieldRow(f, 6))
  const last = out[out.length - 1]
  if (last && last.section.title === REST_SECTION_TITLE) {
    // resolveLayout hat schon einen Sammel-Abschnitt angelegt – nicht zwei
    // gleichnamige Karten untereinander stellen.
    out[out.length - 1] = { section: last.section, rows: [...last.rows, ...restRows] }
    return out
  }
  return [...out, {
    section: out.length ? section(REST_SECTION_TITLE, 'default') : section('Angaben', 'base'),
    rows: restRows,
  }]
})

/** Wie viele Katalogfelder die aktuelle Rolle nicht sehen darf. */
const hiddenCount = computed(() => catalog.value.length - allowed.value.size)

// ── Werte lesbar machen (Logik in lib/processFieldFormat.ts) ─────────────────

const display = (f: FieldDef, raw: unknown): string => fieldValueText(f, raw, props.sources)

// ── Wiederholgruppen ─────────────────────────────────────────────────────────

const isCollection = (f: FieldDef) => f.widget === 'collection'

const rowsOf = (f: FieldDef): Record<string, unknown>[] => collectionEntries(vals.value[f.key])

const subLabel = (sf: SubField): string => subFieldLabel(sf)
const subText = (v: unknown): string => subValueText(v)
</script>

<template>
  <div class="space-y-6">
    <LayoutSection v-for="(b, bi) in blocks" :key="`${bi}:${b.section.title}`" :section="b.section">
      <!-- 12er-Raster wie im Formular; die Spaltenklassen stammen aus der festen
           Tabelle in lib/processLayout.ts (Tailwind findet dynamische
           Klassennamen nicht). -->
      <div class="grid grid-cols-12 gap-4">
        <div v-for="row in b.rows" :key="row.key"
             class="col-span-12" :class="colSpanClass(row.cols)">
          <template v-if="row.kind === 'field'">
            <!-- Wiederholgruppe als kleine Tabelle -->
            <ReadonlyField v-if="isCollection(row.f)" :label="row.f.label || row.f.key">
              <span v-if="!rowsOf(row.f).length" class="text-gray-400 italic">—</span>
              <div v-else class="overflow-x-auto rounded-xl border border-gray-200 dark:border-white/10">
                <table class="w-full text-sm">
                  <thead>
                    <tr class="text-left text-xs text-gray-400 uppercase tracking-wider
                               border-b dark:border-white/[0.06]">
                      <th v-for="sf in row.f.item" :key="sf.key" class="px-4 py-2 font-semibold">
                        {{ subLabel(sf) }}
                      </th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                    <tr v-for="(entry, i) in rowsOf(row.f)" :key="i" class="align-top">
                      <td v-for="sf in row.f.item" :key="sf.key"
                          class="px-4 py-2 text-gray-900 dark:text-white whitespace-pre-wrap">
                        {{ subText(entry[sf.key]) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </ReadonlyField>

            <ReadonlyField
              v-else
              :label="row.f.label || row.f.key"
              :value="display(row.f, vals[row.f.key])"
              :pre="row.f.widget === 'textarea'"
            />
          </template>

          <LayoutDecoration v-else :item="row.item" />
        </div>
      </div>
    </LayoutSection>

    <p v-if="!blocks.length" class="text-sm text-gray-400 italic px-1">
      Keine sichtbaren Angaben.
    </p>

    <p v-if="hiddenCount > 0" class="text-xs text-gray-400 italic px-1">
      Einzelne Felder sind für Ihre Rolle ausgeblendet.
    </p>
  </div>
</template>
