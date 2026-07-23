<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const ANLASS_LABEL: Record<string, string> = {
  kundentermin:         'Kundentermin',
  besuch_niederlassung: 'Besuch Niederlassung',
  sonstiges:            'Sonstiges',
}

const props = defineProps<{ description: any }>()
const b = (k: string) => props.description?.buchung?.[k] ?? '—'
</script>

<template>
  <TicketSection title="Antragsteller" variant="base">
    <TicketFieldGrid>
      <TicketField label="Name" :value="b('antragsteller_name')" />
      <TicketField label="E-Mail" :value="b('antragsteller_email')" />
      <TicketField label="Niederlassung" :value="b('niederlassung')" />
      <TicketField label="Telefonnummer" :value="b('telefonnummer')" />
      <TicketField label="Kostenstelle" :value="b('kostenstelle')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Reisedaten" variant="travel">
    <TicketFieldGrid :cols="3">
      <TicketField label="Anreisedatum" :value="b('anreisedatum')" />
      <TicketField label="Abreisedatum" :value="b('abreisedatum')" />
      <TicketField label="Übernachtungen" :value="b('anzahl_naechte')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Reiseziel" variant="travel">
    <TicketFieldGrid>
      <TicketField label="Ort / Stadt" :value="b('ort_stadt')" />
      <TicketField label="Partner-Hotel" :value="b('partner_hotel')" />
      <TicketField label="Hotelwunsch" :value="b('hotelwunsch')" wide />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Reiseanlass" variant="travel">
    <TicketField label="Art">{{ ANLASS_LABEL[b('reiseanlass')] ?? b('reiseanlass') }}</TicketField>

    <TicketFieldGrid v-if="b('reiseanlass') === 'kundentermin'">
      <TicketField label="Kundenname" :value="b('kunde_name')" />
      <TicketField label="Anschrift" :value="b('kunde_anschrift')" />
      <TicketField label="Grund des Besuchs" :value="b('kunde_grund')" wide pre />
    </TicketFieldGrid>

    <TicketFieldGrid v-if="b('reiseanlass') === 'besuch_niederlassung'">
      <TicketField label="Niederlassung" :value="b('besuch_niederlassung')" />
      <TicketField v-if="b('besuch_begruendung') !== '—'" label="Begründung" :value="b('besuch_begruendung')" wide pre />
    </TicketFieldGrid>

    <TicketFieldGrid v-if="b('reiseanlass') === 'sonstiges'">
      <TicketField label="Begründung" :value="b('sonstiges_grund')" wide pre />
      <TicketField label="Genehmigung durch" :value="b('genehmigung_name')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Budgetvorgaben" variant="travel">
    <TicketField label="Bestätigung">
      {{ b('budget_bestaetigung') === 'unter_120'
        ? 'Kosten ≤ 120 € pro Nacht inkl. Frühstück'
        : b('budget_bestaetigung') === 'abweichung'
          ? 'Abweichung erforderlich'
          : '—' }}
    </TicketField>
    <TicketFieldGrid v-if="b('budget_bestaetigung') === 'abweichung'">
      <TicketField label="Begründung" :value="b('budget_begruendung')" wide pre />
      <TicketField label="Genehmigung durch" :value="b('budget_genehmigung_name')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection v-if="b('besondere_anforderungen') !== '—'" title="Besondere Anforderungen" variant="travel">
    <TicketField label="Anforderungen" :value="b('besondere_anforderungen')" wide pre />
  </TicketSection>
</template>
