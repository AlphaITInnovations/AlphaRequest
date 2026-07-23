<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const h = (k: string) => props.description?.hardware?.[k] ?? '—'
const m = ()          => props.description?.hardware?.monitor ?? {}
const a = ()          => props.description?.hardware?.artikel ?? {}

const zusatz = () => [
  a().Notebook        && 'Notebook',
  a().MiniPC          && 'Mini-PC',
  a().MausUndTastatur && 'Maus & Tastatur',
  a().Headset         && 'Headset',
  a().Webcam          && 'Webcam',
  a().Handy           && 'Handy',
  a().SIM             && 'SIM-Karte',
].filter(Boolean).join(', ') || '—'
</script>

<template>
  <TicketSection title="Basisdaten" variant="base">
    <TicketFieldGrid>
      <TicketField label="Mitarbeitertyp" :value="h('mitarbeiterTyp')" />
      <TicketField label="Vorname" :value="h('vorname')" />
      <TicketField label="Nachname" :value="h('nachname')" />
      <TicketField label="Kostenstelle" :value="h('kostenstelle')" />
      <TicketField label="Firma" :value="h('firma')" />
      <TicketField label="Lieferadresse" wide pre>
        {{ h('addr_strasse') }} {{ h('addr_nr') }}, {{ h('addr_plz') }} {{ h('addr_stadt') }}<template v-if="h('addr_tuerschild') !== '—'"><br>(Türschild: {{ h('addr_tuerschild') }})</template>
      </TicketField>
      <TicketField label="Lieferung bis" :value="h('lieferungBis')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Hardware" variant="it" badge="IT">
    <TicketFieldGrid>
      <TicketField label="Gerätetyp" :value="h('geraet')" />
      <TicketField label="Monitor">{{ m().benoetigt ? `Ja (${m().anzahl}×)` : 'Nein' }}</TicketField>
      <TicketField label="Dockingstation bestellen">{{ a().Dockingstation ? 'Ja' : 'Nein' }}</TicketField>
      <TicketField label="Dockingstation vorhanden">{{ h('dockingVorhanden') === true || h('dockingVorhanden') === 'true' ? 'Ja' : 'Nein' }}</TicketField>
      <TicketField label="Zusätzliche Hardware" wide>{{ zusatz() }}</TicketField>
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Zusatzinformationen" variant="default">
    <TicketField label="Grund der Neubestellung" :value="h('grundBestellung')" pre />
    <TicketField label="Bemerkung" :value="h('bemerkung')" pre />
  </TicketSection>
</template>
