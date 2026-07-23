<script setup lang="ts">
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

// Freitext zu einem Software-Zugriff (z.B. datev_rights)
const swText = (k: string) => props.description?.it?.software?.[k] ?? ''
</script>

<template>
  <!-- Basisdaten -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm p-6 space-y-6">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Basisdaten</h2>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Stammdaten</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Anrede</p><p class="ro-value">{{ b('salutation') }}</p></div>
        <div><p class="ro-label">Vorname</p><p class="ro-value">{{ b('first_name') }}</p></div>
        <div><p class="ro-label">Nachname</p><p class="ro-value">{{ b('last_name') }}</p></div>
        <div><p class="ro-label">Titel</p><p class="ro-value">{{ p('title') }}</p></div>
        <div><p class="ro-label">Eintrittsdatum (laut Vertrag)</p><p class="ro-value">{{ p('start_date') }}</p></div>

        <!-- Privatadresse zusammengefasst -->
        <div class="md:col-span-2 rounded-xl border border-gray-200 dark:border-white/10
                    bg-gray-50/60 dark:bg-white/[0.02] p-4">
          <p class="ro-label mb-2">Privatadresse</p>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2"><p class="ro-label">Straße &amp; Hausnummer</p><p class="ro-value">{{ p('private_street') || p('private_address') }}</p></div>
            <div><p class="ro-label">PLZ</p><p class="ro-value">{{ p('private_zip') }}</p></div>
            <div><p class="ro-label">Ort</p><p class="ro-value">{{ p('private_city') }}</p></div>
          </div>
        </div>

        <div><p class="ro-label">Homeoffice</p><p class="ro-value">{{ p('homeoffice') }}</p></div>
        <div><p class="ro-label">Arbeitszeit (Std./Woche)</p><p class="ro-value">{{ p('weekly_hours') }}</p></div>
        <div><p class="ro-label">Personalnummer</p><p class="ro-value font-mono">{{ p('personal_number') }}</p></div>
      </div>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Organisation</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <p class="ro-label">Abteilung</p>
          <p class="ro-value">
            {{ p('department') === 'Sonstige' ? p('department_other') || 'Sonstige' : p('department') }}
          </p>
        </div>
        <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ b('cost_center') }}</p></div>
        <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ b('location') }}</p></div>
        <div><p class="ro-label">Bundesland</p><p class="ro-value">{{ p('federal_state') }}</p></div>
        <div><p class="ro-label">Firma lt. Arbeitsvertrag</p><p class="ro-value">{{ b('contract_company') }}</p></div>
      </div>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Beziehungen</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Vorgesetzter (HR)</p><p class="ro-value">{{ p('supervisor_hr_name') }}</p></div>
        <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ p('contact_person_name') }}</p></div>
      </div>
    </div>

    <div v-if="description?.it?.timebutler">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Timebutler</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Urlaubsanspruch pro Jahr</p><p class="ro-value">{{ tb('vacation_year') }}</p></div>
        <div><p class="ro-label">Urlaub freigeben</p><p class="ro-value">{{ tb('supervisor_name') }}</p></div>
      </div>
    </div>

    <div v-if="description?.fuhrpark">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Fuhrpark</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Dienstwagen</p><p class="ro-value">{{ f('car') }}</p></div>
        <template v-if="f('car') === 'Ja'">
          <div><p class="ro-label">Fahrzeuggruppe</p><p class="ro-value">{{ f('car_class') }}</p></div>
          <div><p class="ro-label">Benötigt ab</p><p class="ro-value">{{ f('car_from') }}</p></div>
        </template>
      </div>
    </div>
  </div>

  <!-- IT Systemdaten – nur wenn der Abschnitt für den Betrachter sichtbar ist -->
  <div v-if="description?.it" class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm p-6 space-y-6">
    <h2 class="text-base font-semibold text-[#3EAAB8]">IT / Systemdaten</h2>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Firma (Signatur / Webseite)</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Firma</p><p class="ro-value">{{ it('appearance_company') }}</p></div>
      </div>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">E-Mail-Signatur</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Titel (Signatur)</p><p class="ro-value">{{ sig('title') }}</p></div>
        <div><p class="ro-label">Straße</p><p class="ro-value">{{ sig('street') }}</p></div>
        <div><p class="ro-label">Postleitzahl</p><p class="ro-value">{{ sig('zip') }}</p></div>
        <div><p class="ro-label">Ort</p><p class="ro-value">{{ sig('city') }}</p></div>
      </div>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Software-Zugriffe</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">DATEV-Zugriff</p><p class="ro-value">{{ sw('datev') ? 'Ja' : 'Nein' }}</p></div>
        <div v-if="sw('datev') && swText('datev_rights')"><p class="ro-label">Rechte wie Mitarbeiter XY?</p><p class="ro-value whitespace-pre-wrap">{{ swText('datev_rights') }}</p></div>

        <div><p class="ro-label">PersoPro-Zugriff</p><p class="ro-value">{{ sw('persopro') ? 'Ja' : 'Nein' }}</p></div>
        <div v-if="sw('persopro') && swText('persopro_rights')"><p class="ro-label">Welche Zugriffe?</p><p class="ro-value whitespace-pre-wrap">{{ swText('persopro_rights') }}</p></div>

        <div><p class="ro-label">TimeJob-Zugriff</p><p class="ro-value">{{ sw('timejob') ? 'Ja' : 'Nein' }}</p></div>
        <div v-if="sw('timejob') && swText('timejob_rights')"><p class="ro-label">Welche Zugriffe?</p><p class="ro-value whitespace-pre-wrap">{{ swText('timejob_rights') }}</p></div>

        <div><p class="ro-label">Zvoove-Zugriff</p><p class="ro-value">{{ sw('zvoove') ? 'Ja' : 'Nein' }}</p></div>
        <div v-if="sw('zvoove') && swText('zvoove_rights')"><p class="ro-label">Welche Zugriffe?</p><p class="ro-value whitespace-pre-wrap">{{ swText('zvoove_rights') }}</p></div>

        <div class="md:col-span-2" v-if="it('other_systems')">
          <p class="ro-label">Weitere Software</p>
          <p class="ro-value whitespace-pre-wrap">{{ it('other_systems') }}</p>
        </div>
      </div>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Postfächer & Kostenstellen</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <p class="ro-label">Infopostfach der Niederlassung</p>
          <p class="ro-value">{{ description?.it?.mailboxes?.info_mailbox ? 'Ja' : 'Nein' }}</p>
        </div>
        <div><p class="ro-label">Zusätzliche Postfächer?</p><p class="ro-value">{{ mb('additional') }}</p></div>
        <div v-if="mb('additional') === 'Ja'" class="md:col-span-2">
          <p class="ro-label">Postfächer</p>
          <p class="ro-value whitespace-pre-wrap">{{ mb('notes') }}</p>
        </div>
        <div class="md:col-span-2">
          <p class="ro-label">Zusätzliche Kostenstellen / Niederlassungen</p>
          <p class="ro-value whitespace-pre-wrap">{{ it('additional_cost_centers') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label {
  @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5;
}
.ro-value {
  @apply text-sm text-gray-900 dark:text-white;
}
</style>