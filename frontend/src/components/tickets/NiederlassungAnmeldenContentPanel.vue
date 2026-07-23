<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const miete = (k: string) => props.description?.miete?.[k]    ?? '—'
const it    = (k: string) => props.description?.it?.[k]       ?? '—'
const m     = (k: string) => props.description?.marketing?.[k] ?? '—'
const f     = (k: string) => props.description?.fuhrpark?.[k]  ?? '—'
</script>

<template>
  <TicketSection title="Niederlassung" variant="base">
    <TicketFieldGrid>
      <TicketField label="Ort" :value="miete('location')" />
      <TicketField label="Firma" :value="miete('company')" />
      <TicketField label="Wiedereröffnung" :value="miete('reopening')" />
      <TicketField label="Kostenstelle" :value="miete('cost_center')" />
      <TicketField label="Startdatum" :value="miete('start_date')" />
      <TicketField label="Firma an Klingel sichtbar?">
        {{ miete('sign_visible') }}
        <span v-if="miete('sign_visible') === 'Nein'" class="block text-xs text-amber-600 dark:text-amber-400 mt-0.5">
          📌 Bitte Zettel oder ähnliches anbringen.
        </span>
      </TicketField>
      <TicketField label="Adresse" :value="miete('address')" wide pre />
      <TicketField label="Vorgesetzter Niederlassung" :value="miete('location_supervisor_name')" />
      <TicketField label="Ansprechpartner" :value="miete('contact_person_name')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="IT" variant="it" badge="IT">
    <TicketFieldGrid>
      <TicketField label="Serverschrank vorhanden?" :value="it('server_rack')" />
      <TicketField label="Netzwerkverkabelung" :value="it('network_cabling')" />
      <TicketField label="DSL/Glasfaser-Dose installiert?" :value="it('line_installed')" wide />
      <template v-if="it('line_installed') === 'Ja'">
        <TicketField label="Art / Anschluss" :value="it('line_type')" />
        <TicketField label="Standort" :value="it('line_location')" wide pre />
      </template>
      <template v-if="it('line_installed') === 'Nein'">
        <TicketField label="Vermieter – Name" :value="it('landlord_name')" />
        <TicketField label="Vermieter – Kontakt" :value="it('landlord_contact')" />
      </template>
    </TicketFieldGrid>
    <div v-if="it('line_installed') === 'Nein'"
         class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
      📌 Vermieter wird mit der Installation beauftragt.
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
