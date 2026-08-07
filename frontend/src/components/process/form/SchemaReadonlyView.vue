<script setup lang="ts">
/**
 * Nur-Lese-Ansicht der Werte eines Prozess-Auftrags.
 *
 * Sichtbarkeit läuft über visibleFieldKeys() – denselben Filter, den der Server
 * beim Ausliefern anwendet. Werden Felder ausgeblendet, weist ein Hinweis am
 * Fuß darauf hin: sonst wirkt eine vertrauliche Angabe schlicht wie „nicht
 * ausgefüllt".
 */
import { computed } from 'vue'
import type { FieldDef, OptionSources, PhaseDef, ProcessDefinition, SubField } from '@/types/process'
import { visibleFieldKeys } from '@/lib/processSim'
import type { SimViewer } from '@/lib/processSim'
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{
  definition: ProcessDefinition
  values: Record<string, unknown>
  viewer: SimViewer
  sources?: OptionSources
  phase?: PhaseDef | null
}>()

const catalog = computed<FieldDef[]>(() => props.definition?.fields ?? [])
const vals = computed<Record<string, unknown>>(() => props.values ?? {})
const byKey = computed(() => new Map(catalog.value.map((f) => [f.key, f])))

const allowed = computed<Set<string>>(() =>
  props.definition ? visibleFieldKeys(props.definition, props.viewer) : new Set<string>())

/** Felder der übergebenen Phase in Phasen-Reihenfolge (ohne ausgeblendete). */
const phaseFields = computed<FieldDef[]>(() => {
  const p = props.phase
  if (!p) return []
  const seen = new Set<string>()
  const out: FieldDef[] = []
  for (const ref of p.fields ?? []) {
    if (ref.mode === 'hidden' || seen.has(ref.ref)) continue
    const f = byKey.value.get(ref.ref)
    if (!f || !allowed.value.has(f.key)) continue
    seen.add(ref.ref)
    out.push(f)
  }
  return out
})

const restFields = computed<FieldDef[]>(() => {
  const inPhase = new Set(phaseFields.value.map((f) => f.key))
  return catalog.value.filter((f) => allowed.value.has(f.key) && !inPhase.has(f.key))
})

interface Section { title: string; variant: 'base' | 'default'; fields: FieldDef[] }

const sections = computed<Section[]>(() => {
  const out: Section[] = []
  if (phaseFields.value.length) {
    out.push({
      title: props.phase?.label || props.phase?.key || 'Angaben',
      variant: 'base',
      fields: phaseFields.value,
    })
  }
  if (restFields.value.length) {
    out.push({
      title: out.length ? 'Weitere Angaben' : 'Angaben',
      variant: out.length ? 'default' : 'base',
      fields: restFields.value,
    })
  }
  return out
})

/** Wie viele Katalogfelder die aktuelle Rolle nicht sehen darf. */
const hiddenCount = computed(() => catalog.value.length - allowed.value.size)

// ── Werte lesbar machen ──────────────────────────────────────────────────────

function userName(id: string): string {
  return props.sources?.users.find((u) => u.id === id)?.displayName || id
}
function groupName(id: string): string {
  return props.sources?.groups.find((g) => g.id === id)?.name || id
}

/** Einen einzelnen Wert über Optionen bzw. Stammdaten in einen Namen übersetzen. */
function labelOfValue(f: FieldDef, raw: unknown): string {
  const v = String(raw)
  if (f.widget === 'user' || f.optionsSource === 'users') return userName(v)
  if (f.widget === 'group' || f.optionsSource === 'groups') return groupName(v)
  const opt = (f.options ?? []).find((o) => o.value === v)
  return opt ? (opt.label ?? opt.value) : v
}

function display(f: FieldDef, raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '—'
  if (typeof raw === 'boolean') return raw ? 'Ja' : 'Nein'
  if (Array.isArray(raw)) {
    return raw.length ? raw.map((x) => labelOfValue(f, x)).join(', ') : '—'
  }
  if (typeof raw === 'object') return JSON.stringify(raw)
  return labelOfValue(f, raw)
}

// ── Wiederholgruppen ─────────────────────────────────────────────────────────

const isCollection = (f: FieldDef) => f.widget === 'collection'

function rowsOf(f: FieldDef): Record<string, unknown>[] {
  const raw = vals.value[f.key]
  if (!Array.isArray(raw)) return []
  return raw.map((e) =>
    e && typeof e === 'object' && !Array.isArray(e) ? (e as Record<string, unknown>) : {})
}

function subLabel(sf: SubField): string {
  return sf.label || sf.key
}

function subText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (Array.isArray(v)) return v.length ? v.map((x) => String(x)).join(', ') : '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
</script>

<template>
  <div class="space-y-6">
    <TicketSection v-for="s in sections" :key="s.title" :title="s.title" :variant="s.variant">
      <TicketFieldGrid :cols="2">
        <template v-for="f in s.fields" :key="f.key">
          <!-- Wiederholgruppe als kleine Tabelle über die volle Breite -->
          <TicketField v-if="isCollection(f)" :label="f.label || f.key" wide>
            <span v-if="!rowsOf(f).length" class="text-gray-400 italic">—</span>
            <div v-else class="overflow-x-auto rounded-xl border border-gray-200 dark:border-white/10">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-left text-xs text-gray-400 uppercase tracking-wider
                             border-b dark:border-white/[0.06]">
                    <th v-for="sf in f.item" :key="sf.key" class="px-4 py-2 font-semibold">
                      {{ subLabel(sf) }}
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                  <tr v-for="(row, i) in rowsOf(f)" :key="i" class="align-top">
                    <td v-for="sf in f.item" :key="sf.key"
                        class="px-4 py-2 text-gray-900 dark:text-white whitespace-pre-wrap">
                      {{ subText(row[sf.key]) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TicketField>

          <TicketField
            v-else
            :label="f.label || f.key"
            :value="display(f, vals[f.key])"
            :wide="f.widget === 'textarea'"
            :pre="f.widget === 'textarea'"
          />
        </template>
      </TicketFieldGrid>
    </TicketSection>

    <p v-if="!sections.length" class="text-sm text-gray-400 italic px-1">
      Keine sichtbaren Angaben.
    </p>

    <p v-if="hiddenCount > 0" class="text-xs text-gray-400 italic px-1">
      Einzelne Felder sind für Ihre Rolle ausgeblendet.
    </p>
  </div>
</template>
