<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

const p  = (k: string) => props.description?.personal?.[k] ?? '—'
const it = (k: string) => props.description?.it?.[k]       ?? '—'
const f  = (k: string) => props.description?.fuhrpark?.[k] ?? '—'
</script>

<template>
  <TicketSection title="Basisdaten" variant="base">
    <TicketFieldGrid>
      <TicketField label="Vorname" :value="p('first_name')" />
      <TicketField label="Nachname" :value="p('last_name')" />
      <TicketField label="Kostenstelle" :value="p('cost_center')" />
      <TicketField label="Firma lt. Arbeitsvertrag" :value="p('contract_company')" />
      <TicketField label="Austrittsdatum" :value="p('exit_date')" />
      <TicketField label="Abfindungsvereinbarung" :value="p('severance_agreement')" />
    </TicketFieldGrid>
  </TicketSection>

  <TicketSection title="IT" variant="it" badge="IT">
    <TicketFieldGrid>
      <TicketField label="Mailweiterleitung?" :value="it('mail_forwarding')" />
      <TicketField label="Weiterleiten an">{{ it('mail_forwarding') === 'Ja' ? it('mail_forward_to') : '—' }}</TicketField>
      <TicketField label="Postfachzugriff gewähren?" :value="it('mailbox_access')" />
      <TicketField label="Zugriff für" wide pre>{{ it('mailbox_access') === 'Ja' ? it('mailbox_access_for') : '—' }}</TicketField>
      <TicketField label="Abwesenheitsnotiz?" :value="it('auto_reply')" />
      <TicketField label="Text der Abwesenheitsnotiz" wide pre mono>{{ it('auto_reply') === 'Ja' ? it('auto_reply_text') : '—' }}</TicketField>
    </TicketFieldGrid>

    <div class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
      <p class="font-semibold mb-1">📌 Wichtige Hinweise</p>
      <ul class="list-disc pl-4 space-y-1">
        <li><strong>Mailweiterleitung</strong> und <strong>Postfachzugriff</strong> sind jeweils <strong>maximal 30 Tage</strong> möglich.</li>
        <li>Postfächer werden gesichert – <strong>neue E-Mails werden nicht mehr zugestellt.</strong></li>
        <li>Abwesenheitsnotiz ggf. Platzhalter prüfen: <code>&lt;Name&gt;</code>, <code>&lt;Ersatzmailadresse&gt;</code></li>
      </ul>
    </div>
  </TicketSection>

  <TicketSection title="Fuhrpark" variant="fuhrpark" badge="Fuhrpark">
    <TicketFieldGrid>
      <TicketField label="Dienstwagen vorhanden?" :value="f('car')" />
      <TicketField label="Rückgabedatum">{{ f('car') === 'Ja' ? f('car_return_date') : '—' }}</TicketField>
    </TicketFieldGrid>
  </TicketSection>
</template>
