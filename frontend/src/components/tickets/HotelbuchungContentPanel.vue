<script setup lang="ts">
const props = defineProps<{ description: any }>()

const ANLASS_LABEL: Record<string, string> = {
  kundentermin:         'Kundentermin',
  besuch_niederlassung: 'Besuch Niederlassung',
  sonstiges:            'Sonstiges',
}

const b = (k: string) => props.description?.buchung?.[k] ?? '—'
</script>

<template>
  <!-- Antragsteller -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Antragsteller</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Name</p><p class="ro-value">{{ b('antragsteller_name') }}</p></div>
      <div><p class="ro-label">E-Mail</p><p class="ro-value">{{ b('antragsteller_email') }}</p></div>
      <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ b('niederlassung') }}</p></div>
      <div><p class="ro-label">Telefonnummer</p><p class="ro-value">{{ b('telefonnummer') }}</p></div>
      <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ b('kostenstelle') }}</p></div>
    </div>
  </div>

  <!-- Reisedaten -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Reisedaten</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div><p class="ro-label">Anreisedatum</p><p class="ro-value">{{ b('anreisedatum') }}</p></div>
      <div><p class="ro-label">Abreisedatum</p><p class="ro-value">{{ b('abreisedatum') }}</p></div>
      <div><p class="ro-label">Übernachtungen</p><p class="ro-value">{{ b('anzahl_naechte') }}</p></div>
    </div>
  </div>

  <!-- Reiseziel -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Reiseziel</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Ort / Stadt</p><p class="ro-value">{{ b('ort_stadt') }}</p></div>
      <div><p class="ro-label">Partner-Hotel</p><p class="ro-value">{{ b('partner_hotel') }}</p></div>
      <div class="md:col-span-2"><p class="ro-label">Hotelwunsch</p><p class="ro-value">{{ b('hotelwunsch') }}</p></div>
    </div>
  </div>

  <!-- Reiseanlass -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Reiseanlass</h2>
    <div>
      <p class="ro-label">Art</p>
      <p class="ro-value font-medium">{{ ANLASS_LABEL[b('reiseanlass')] ?? b('reiseanlass') }}</p>
    </div>

    <template v-if="b('reiseanlass') === 'kundentermin'">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        <div><p class="ro-label">Kundenname</p><p class="ro-value">{{ b('kunde_name') }}</p></div>
        <div><p class="ro-label">Anschrift</p><p class="ro-value">{{ b('kunde_anschrift') }}</p></div>
        <div class="md:col-span-2"><p class="ro-label">Grund des Besuchs</p><p class="ro-value whitespace-pre-wrap">{{ b('kunde_grund') }}</p></div>
      </div>
    </template>

    <template v-if="b('reiseanlass') === 'besuch_niederlassung'">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ b('besuch_niederlassung') }}</p></div>
        <div class="md:col-span-2" v-if="b('besuch_begruendung') !== '—'">
          <p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('besuch_begruendung') }}</p>
        </div>
      </div>
    </template>

    <template v-if="b('reiseanlass') === 'sonstiges'">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        <div class="md:col-span-2"><p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('sonstiges_grund') }}</p></div>
        <div><p class="ro-label">Genehmigung durch</p><p class="ro-value">{{ b('genehmigung_name') }}</p></div>
      </div>
    </template>
  </div>

  <!-- Budgetvorgaben -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Budgetvorgaben</h2>
    <div>
      <p class="ro-label">Bestätigung</p>
      <p class="ro-value font-medium">
        {{ b('budget_bestaetigung') === 'unter_120'
          ? 'Kosten ≤ 120 € pro Nacht inkl. Frühstück'
          : b('budget_bestaetigung') === 'abweichung'
            ? 'Abweichung erforderlich'
            : '—' }}
      </p>
    </div>
    <template v-if="b('budget_bestaetigung') === 'abweichung'">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        <div class="md:col-span-2"><p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('budget_begruendung') }}</p></div>
        <div><p class="ro-label">Genehmigung durch</p><p class="ro-value">{{ b('budget_genehmigung_name') }}</p></div>
      </div>
    </template>
  </div>

  <!-- Besondere Anforderungen -->
  <div v-if="b('besondere_anforderungen') !== '—'"
       class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Besondere Anforderungen</h2>
    <p class="text-sm text-gray-900 dark:text-white whitespace-pre-wrap">{{ b('besondere_anforderungen') }}</p>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>