<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const HARDWARE_LABEL: Record<string, string> = {
  return_it:       'Wird an die IT gesendet',
  transfer_branch: 'Transfer in andere Niederlassung',
}

const p  = (k: string) => props.description?.personal?.[k]  ?? '—'
const it = (k: string) => props.description?.it?.[k]        ?? '—'
const f  = (k: string) => props.description?.fuhrpark?.[k]  ?? '—'
</script>

<template>
  <TicketSection title="Personalabteilung" variant="hr" badge="Personalabteilung">
    <TicketFieldGrid>
      <TicketField label="Niederlassung" :value="p('location')" />
      <TicketField label="Schließungsdatum" :value="p('closing_date')" />
      <TicketField label="Adresse" :value="p('address')" wide pre />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="IT" variant="it" badge="IT">
    <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-5 space-y-3">
      <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
      <div class="flex items-start gap-3 text-sm text-red-800 dark:text-red-200">
        <span>{{ it('confirm_dsl_cancel') ? '✅' : '⬜' }}</span>
        <div>
          <strong>Die DSL/Internetleitung wird gekündigt.</strong>
          <p class="text-xs mt-0.5 opacity-75">Bestätigt: {{ it('confirm_dsl_cancel') ? 'Ja' : 'Nein' }}</p>
        </div>
      </div>
      <div class="flex items-start gap-3 text-sm text-red-800 dark:text-red-200">
        <span>{{ it('confirm_landline_cancel') ? '✅' : '⬜' }}</span>
        <div>
          <strong>Die Festnetzrufnummer wird gekündigt und ist danach nicht mehr erreichbar!</strong>
          <p class="text-xs mt-0.5 opacity-75">Bestätigt: {{ it('confirm_landline_cancel') ? 'Ja' : 'Nein' }}</p>
        </div>
      </div>
    </div>

    <TicketFieldGrid>
      <TicketField label="Umgang mit Hardware" wide>{{ HARDWARE_LABEL[it('hardware_action')] ?? it('hardware_action') }}</TicketField>
      <TicketField v-if="it('hardware_action') === 'transfer_branch'" label="Ziel-Niederlassung" :value="it('transfer_target')" wide pre />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="Fuhrpark" variant="fuhrpark" badge="Fuhrpark">
    <TicketFieldGrid>
      <TicketField label="Poolfahrzeuge vor Ort?" :value="f('pool_cars')" />
      <TicketField v-if="f('pool_cars') === 'Ja'" label="Rückgabedatum" :value="f('return_date')" />
    </TicketFieldGrid>
  </TicketSection>
</template>
