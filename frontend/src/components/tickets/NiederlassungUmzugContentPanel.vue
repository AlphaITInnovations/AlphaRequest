<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const LEASE_LABEL: Record<string, string> = {
  cancel: 'Wird gekündigt',
  keep:   'Bleibt bestehen',
}

const ma  = (k: string) => props.description?.miete_alt?.[k]  ?? '—'
const mn  = (k: string) => props.description?.miete_neu?.[k]  ?? '—'
const ia  = (k: string) => props.description?.it_alt?.[k]     ?? '—'
const inn = (k: string) => props.description?.it_neu?.[k]     ?? '—'
const m   = (k: string) => props.description?.marketing?.[k]  ?? '—'
const f   = (k: string) => props.description?.fuhrpark?.[k]   ?? '—'
</script>

<template>
  <TicketSection title="Miete" variant="base">
    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Alt (bisherige Niederlassung)</h3>
      <TicketFieldGrid>
        <TicketField label="Ort (alt)" :value="ma('location')" />
        <TicketField label="Firma (alt)" :value="ma('company')" />
        <TicketField label="Mietvertrag" wide>{{ LEASE_LABEL[ma('lease_action')] ?? ma('lease_action') }}</TicketField>
        <TicketField v-if="ma('lease_action') === 'cancel'" label="Kündigungsdatum" :value="ma('lease_cancel_date')" />
        <TicketField v-if="ma('lease_action') === 'keep'" label="Begründung" :value="ma('lease_keep_reason')" wide pre />
      </TicketFieldGrid>
    </div>

    <div class="pt-5 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Neu (neue Niederlassung)</h3>
      <TicketFieldGrid>
        <TicketField label="Ort (neu)" :value="mn('location')" />
        <TicketField label="Firma (neu)" :value="mn('company')" />
        <TicketField label="Firma an Klingel sichtbar?">
          {{ mn('sign_visible') }}
          <span v-if="mn('sign_visible') === 'Nein'" class="block text-xs text-amber-600 dark:text-amber-400 mt-0.5">📌 Zettel anbringen</span>
        </TicketField>
        <TicketField label="Wiedereröffnung" :value="mn('reopening')" />
        <TicketField label="Kostenstelle" :value="mn('cost_center')" />
        <TicketField label="Startdatum" :value="mn('start_date')" />
        <TicketField label="Adresse" :value="mn('address')" wide pre />
        <TicketField label="Vorgesetzter" :value="mn('location_supervisor_name')" />
        <TicketField label="Ansprechpartner" :value="mn('contact_person_name')" />
      </TicketFieldGrid>
    </div>
  </TicketSection>

  <TicketSection title="IT" variant="it" badge="IT">
    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Alt</h3>
      <div v-if="ma('lease_action') === 'cancel'" class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-4 space-y-2">
        <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
        <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
          <span>{{ ia('confirm_dsl_cancel') ? '✅' : '⬜' }}</span>
          <div><strong>DSL/Internet gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_dsl_cancel') ? 'Ja' : 'Nein' }}</p></div>
        </div>
        <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
          <span>{{ ia('confirm_landline_cancel') ? '✅' : '⬜' }}</span>
          <div><strong>Festnetz gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_landline_cancel') ? 'Ja' : 'Nein' }}</p></div>
        </div>
      </div>
      <p v-else class="text-sm text-gray-400 italic">Mietvertrag bleibt bestehen – keine IT-Abbauschritte erforderlich.</p>
    </div>

    <div class="pt-4 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Neu</h3>
      <TicketFieldGrid>
        <TicketField label="Serverschrank vorhanden?" :value="inn('server_rack')" />
        <TicketField label="Netzwerkverkabelung" :value="inn('network_cabling')" />
        <TicketField label="DSL/Glasfaser-Dose installiert?" :value="inn('line_installed')" wide />
        <template v-if="inn('line_installed') === 'Ja'">
          <TicketField label="Art / Anschluss" :value="inn('line_type')" />
          <TicketField label="Standort" :value="inn('line_location')" wide pre />
        </template>
        <template v-if="inn('line_installed') === 'Nein'">
          <TicketField label="Vermieter – Name" :value="inn('landlord_name')" />
          <TicketField label="Vermieter – Kontakt" :value="inn('landlord_contact')" />
        </template>
      </TicketFieldGrid>
      <div v-if="inn('line_installed') === 'Nein'"
           class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
        📌 Vermieter wird mit der Installation beauftragt.
      </div>
    </div>
  </TicketSection>

  <TicketSection title="Marketing" variant="marketing" badge="Marketing">
    <TicketField label="Öffnungszeiten" :value="m('opening_hours')" pre />
  </TicketSection>

  <TicketSection title="Fuhrpark" variant="fuhrpark" badge="Fuhrpark">
    <TicketFieldGrid>
      <TicketField label="Poolfahrzeuge benötigt?" :value="f('pool_cars')" />
      <TicketField v-if="f('pool_cars') === 'Ja'" label="Benötigt ab" :value="f('pool_cars_from')" />
    </TicketFieldGrid>
  </TicketSection>
</template>
