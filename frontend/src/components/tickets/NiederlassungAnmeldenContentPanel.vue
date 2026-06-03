<script setup lang="ts">
const props = defineProps<{ description: any }>()

const miete = (k: string) => props.description?.miete?.[k]    ?? '—'
const it    = (k: string) => props.description?.it?.[k]       ?? '—'
const m     = (k: string) => props.description?.marketing?.[k] ?? '—'
const f     = (k: string) => props.description?.fuhrpark?.[k]  ?? '—'
</script>

<template>
  <!-- Niederlassung -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Niederlassung</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Ort</p><p class="ro-value">{{ miete('location') }}</p></div>
      <div><p class="ro-label">Firma</p><p class="ro-value">{{ miete('company') }}</p></div>
      <div><p class="ro-label">Wiedereröffnung</p><p class="ro-value">{{ miete('reopening') }}</p></div>
      <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ miete('cost_center') }}</p></div>
      <div><p class="ro-label">Startdatum</p><p class="ro-value">{{ miete('start_date') }}</p></div>
      <div>
        <p class="ro-label">Firma an Klingel sichtbar?</p>
        <p class="ro-value">{{ miete('sign_visible') }}</p>
        <p v-if="miete('sign_visible') === 'Nein'" class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
          📌 Bitte Zettel oder ähnliches anbringen.
        </p>
      </div>
      <div class="md:col-span-2"><p class="ro-label">Adresse</p><p class="ro-value whitespace-pre-wrap">{{ miete('address') }}</p></div>
      <div><p class="ro-label">Vorgesetzter Niederlassung</p><p class="ro-value">{{ miete('location_supervisor_name') }}</p></div>
      <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ miete('contact_person_name') }}</p></div>
    </div>
  </div>

  <!-- IT -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">IT</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Serverschrank vorhanden?</p><p class="ro-value">{{ it('server_rack') }}</p></div>
      <div><p class="ro-label">Netzwerkverkabelung</p><p class="ro-value">{{ it('network_cabling') }}</p></div>
      <div class="md:col-span-2"><p class="ro-label">DSL/Glasfaser-Dose installiert?</p><p class="ro-value">{{ it('line_installed') }}</p></div>
      <template v-if="it('line_installed') === 'Ja'">
        <div><p class="ro-label">Art / Anschluss</p><p class="ro-value">{{ it('line_type') }}</p></div>
        <div class="md:col-span-2"><p class="ro-label">Standort</p><p class="ro-value whitespace-pre-wrap">{{ it('line_location') }}</p></div>
      </template>
      <template v-if="it('line_installed') === 'Nein'">
        <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          📌 Vermieter wird mit der Installation beauftragt.
        </div>
        <div><p class="ro-label">Vermieter – Name</p><p class="ro-value">{{ it('landlord_name') }}</p></div>
        <div><p class="ro-label">Vermieter – Kontakt</p><p class="ro-value">{{ it('landlord_contact') }}</p></div>
      </template>
    </div>
  </div>

  <!-- Marketing -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-2">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Marketing</h2>
    <p class="ro-label">Öffnungszeiten</p>
    <p class="ro-value whitespace-pre-wrap">{{ m('opening_hours') }}</p>
  </div>

  <!-- Fuhrpark -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Fuhrpark</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Poolfahrzeuge benötigt?</p><p class="ro-value">{{ f('pool_cars') }}</p></div>
      <div v-if="f('pool_cars') === 'Ja'"><p class="ro-label">Benötigt ab</p><p class="ro-value">{{ f('pool_cars_from') }}</p></div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>