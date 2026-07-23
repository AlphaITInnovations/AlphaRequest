<script setup lang="ts">
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketFieldGrid from '@/components/tickets/TicketFieldGrid.vue'
import TicketField from '@/components/tickets/TicketField.vue'

const props = defineProps<{ description: any }>()

// Basisdaten (eigener Block); Fallback auf personal für Alt-Tickets vor der Umstellung.
const b   = (k: string) => props.description?.base?.[k] ?? props.description?.personal?.[k] ?? '—'
const p   = (k: string) => props.description?.personal?.[k]          ?? '—'
const it  = (k: string) => props.description?.it?.[k]                ?? '—'
const sig = (k: string) => props.description?.it?.signature?.[k]     ?? '—'
const tb  = (k: string) => props.description?.it?.timebutler?.[k]    ?? '—'
const sw  = (k: string) => props.description?.it?.software?.[k]      ?? false
const mb  = (k: string) => props.description?.it?.mailboxes?.[k]     ?? '—'
const f   = (k: string) => props.description?.fuhrpark?.[k]          ?? '—'
const swText = (k: string) => props.description?.it?.software?.[k] ?? ''
</script>

<template>
  <!-- Basisdaten – für jede beteiligte Fachabteilung sichtbar -->
  <TicketSection title="Basisdaten" variant="base">
    <TicketFieldGrid>
      <TicketField label="Anrede" :value="b('salutation')" />
      <TicketField label="Vorname" :value="b('first_name')" />
      <TicketField label="Nachname" :value="b('last_name')" />
      <TicketField label="Firma lt. Arbeitsvertrag" :value="b('contract_company')" />
      <TicketField label="Niederlassung" :value="b('location')" />
      <TicketField label="Kostenstelle" :value="b('cost_center')" />
    </TicketFieldGrid>
  </TicketSection>

  <!-- Personalabteilung (HR) -->
  <TicketSection v-if="description?.personal" title="Stammdaten" variant="hr" badge="Personalabteilung">
    <div class="space-y-3">
      <TicketFieldGrid>
        <TicketField label="Titel" :value="p('title')" />
        <TicketField label="Eintrittsdatum (laut Vertrag)" :value="p('start_date')" />
        <TicketField label="Straße & Hausnummer" wide>{{ p('private_street') !== '—' ? p('private_street') : p('private_address') }}</TicketField>
        <TicketField label="PLZ" :value="p('private_zip')" />
        <TicketField label="Ort" :value="p('private_city')" />
        <TicketField label="Homeoffice" :value="p('homeoffice')" />
        <TicketField label="Arbeitszeit (Std./Woche)" :value="p('weekly_hours')" />
        <TicketField label="Personalnummer" :value="p('personal_number')" mono />
      </TicketFieldGrid>
    </div>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Organisation & Beziehungen</h3>
      <TicketFieldGrid>
        <TicketField label="Abteilung">{{ p('department') === 'Sonstige' ? (p('department_other') !== '—' ? p('department_other') : 'Sonstige') : p('department') }}</TicketField>
        <TicketField label="Bundesland" :value="p('federal_state')" />
        <TicketField label="Vorgesetzter (HR)" :value="p('supervisor_hr_name')" />
        <TicketField label="Ansprechpartner" :value="p('contact_person_name')" />
      </TicketFieldGrid>
    </div>
  </TicketSection>

  <!-- IT / Systemdaten -->
  <TicketSection v-if="description?.it" title="IT / Systemdaten" variant="it" badge="IT">
    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Firma & E-Mail-Signatur</h3>
      <TicketFieldGrid>
        <TicketField label="Firma (Signatur / Webseite)" :value="it('appearance_company')" />
        <TicketField label="Titel (Signatur)" :value="sig('title')" />
        <TicketField label="Straße" :value="sig('street')" />
        <TicketField label="Postleitzahl" :value="sig('zip')" />
        <TicketField label="Ort" :value="sig('city')" />
      </TicketFieldGrid>
    </div>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Software-Zugriffe</h3>
      <TicketFieldGrid>
        <TicketField label="DATEV-Zugriff">{{ sw('datev') ? 'Ja' : 'Nein' }}</TicketField>
        <TicketField v-if="sw('datev') && swText('datev_rights')" label="Rechte wie Mitarbeiter XY?" :value="swText('datev_rights')" pre />
        <TicketField label="PersoPro-Zugriff">{{ sw('persopro') ? 'Ja' : 'Nein' }}</TicketField>
        <TicketField v-if="sw('persopro') && swText('persopro_rights')" label="Welche Zugriffe?" :value="swText('persopro_rights')" pre />
        <TicketField label="TimeJob-Zugriff">{{ sw('timejob') ? 'Ja' : 'Nein' }}</TicketField>
        <TicketField v-if="sw('timejob') && swText('timejob_rights')" label="Welche Zugriffe?" :value="swText('timejob_rights')" pre />
        <TicketField label="Zvoove-Zugriff">{{ sw('zvoove') ? 'Ja' : 'Nein' }}</TicketField>
        <TicketField v-if="sw('zvoove') && swText('zvoove_rights')" label="Welche Zugriffe?" :value="swText('zvoove_rights')" pre />
        <TicketField v-if="it('other_systems') !== '—'" label="Weitere Software" :value="it('other_systems')" wide pre />
      </TicketFieldGrid>
    </div>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Postfächer & Kostenstellen</h3>
      <TicketFieldGrid>
        <TicketField label="Infopostfach der Niederlassung">{{ description?.it?.mailboxes?.info_mailbox ? 'Ja' : 'Nein' }}</TicketField>
        <TicketField label="Zusätzliche Postfächer?" :value="mb('additional')" />
        <TicketField v-if="mb('additional') === 'Ja'" label="Postfächer" :value="mb('notes')" wide pre />
        <TicketField label="Zusätzliche Kostenstellen / Niederlassungen" :value="it('additional_cost_centers')" wide pre />
      </TicketFieldGrid>
    </div>

    <div v-if="description?.it?.timebutler" class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Timebutler</h3>
      <TicketFieldGrid>
        <TicketField label="Urlaubsanspruch pro Jahr" :value="tb('vacation_year')" />
        <TicketField label="Urlaub freigeben" :value="tb('supervisor_name')" />
      </TicketFieldGrid>
    </div>
  </TicketSection>

  <!-- Fuhrpark -->
  <TicketSection v-if="description?.fuhrpark" title="Fuhrpark" variant="fuhrpark" badge="Fuhrpark">
    <TicketFieldGrid>
      <TicketField label="Dienstwagen" :value="f('car')" />
      <template v-if="f('car') === 'Ja'">
        <TicketField label="Fahrzeuggruppe" :value="f('car_class')" />
        <TicketField label="Benötigt ab" :value="f('car_from')" />
      </template>
    </TicketFieldGrid>
  </TicketSection>
</template>
