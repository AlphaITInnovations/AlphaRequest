<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const b = (k: string) => props.description?.base?.[k]     ?? '—'
const p = (k: string) => props.description?.personal?.[k] ?? '—'
</script>

<template>
  <!-- Basisdaten – Grundlage für den Arbeitsvertrag (in P2 für alle Fachabteilungen sichtbar) -->
  <TicketSection title="Basisdaten" variant="base">
    <TicketFieldGrid>
      <TicketField label="Anrede" :value="b('salutation')" />
      <TicketField label="Vorname" :value="b('first_name')" />
      <TicketField label="Nachname" :value="b('last_name')" />
      <TicketField label="Titel" :value="p('title')" />
      <TicketField label="Firma lt. Arbeitsvertrag" :value="b('contract_company')" />
      <TicketField label="Niederlassung" :value="b('location')" />
      <TicketField label="Kostenstelle" :value="b('cost_center')" mono />
      <TicketField label="Arbeitsbeginn (laut Vertrag)" :value="b('start_date')" />
    </TicketFieldGrid>
  </TicketSection>

  <!-- Gehalt & Konditionen – nur Personalabteilung/Admin (serverseitig gefiltert);
       für alle anderen ist der Block nicht vorhanden und wird ausgeblendet. -->
  <TicketSection v-if="description?.personal?.salary || description?.personal?.conditions"
                 title="Gehalt & Konditionen" variant="hr" badge="Personalabteilung">
    <TicketFieldGrid>
      <TicketField label="Gehalt" :value="p('salary')" />
      <TicketField label="Konditionen" :value="p('conditions')" wide pre />
    </TicketFieldGrid>
  </TicketSection>
</template>
