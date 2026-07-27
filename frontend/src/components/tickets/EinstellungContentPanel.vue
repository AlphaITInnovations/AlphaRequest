<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const b = (k: string) => props.description?.base?.[k] ?? '—'
const c = (k: string) => props.description?.confidential?.[k] ?? '—'
const title = () => props.description?.personal?.title ?? '—'
</script>

<template>
  <!-- Basisdaten – für jede beteiligte Fachabteilung sichtbar (in P2) -->
  <TicketSection title="Basisdaten" variant="base">
    <TicketFieldGrid>
      <TicketField label="Anrede" :value="b('salutation')" />
      <TicketField label="Vorname" :value="b('first_name')" />
      <TicketField label="Nachname" :value="b('last_name')" />
      <TicketField label="Titel" :value="title()" />
      <TicketField label="Firma lt. Arbeitsvertrag" :value="b('contract_company')" />
      <TicketField label="Niederlassung" :value="b('location')" />
      <TicketField label="Kostenstelle" :value="b('cost_center')" />
      <TicketField label="Arbeitsbeginn (laut Vertrag)" :value="b('start_date')" />
    </TicketFieldGrid>
  </TicketSection>

  <!-- Vertrauliche Informationen – NUR Voll-Sicht (Ersteller/Oversight/Bearbeiter) -->
  <TicketSection title="Vertrauliche Informationen" variant="default" badge="Vertraulich">
    <TicketFieldGrid>
      <TicketField label="Gehalt" :value="c('salary')" />
      <TicketField label="Konditionen" :value="c('conditions')" wide pre />
    </TicketFieldGrid>
  </TicketSection>
</template>
