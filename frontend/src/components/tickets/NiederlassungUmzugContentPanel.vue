<script setup lang="ts">
const props = defineProps<{ description: any }>()

const LEASE_LABEL: Record<string, string> = {
  cancel: 'Wird gekündigt',
  keep:   'Bleibt bestehen',
}

const ma  = (k: string) => props.description?.miete_alt?.[k]  ?? '—'
const mn  = (k: string) => props.description?.miete_neu?.[k]  ?? '—'
const ia  = (k: string) => props.description?.it_alt?.[k]     ?? '—'
const inn = (k: string) => props.description?.it_neu?.[k]     ?? '—'
const m   = (k: string) => props.description?.marketing?.[k]  ?? '—'
const f   = (k: string) => props.description?.fuhrpark?.[k]   ?? '—'
</script>

<template>
  <!-- Miete -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-6">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Miete</h2>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Alt (bisherige Niederlassung)</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Ort (alt)</p><p class="ro-value">{{ ma('location') }}</p></div>
        <div><p class="ro-label">Firma (alt)</p><p class="ro-value">{{ ma('company') }}</p></div>
        <div class="md:col-span-2">
          <p class="ro-label">Mietvertrag</p>
          <p class="ro-value">{{ LEASE_LABEL[ma('lease_action')] ?? ma('lease_action') }}</p>
        </div>
        <div v-if="ma('lease_action') === 'cancel'">
          <p class="ro-label">Kündigungsdatum</p><p class="ro-value">{{ ma('lease_cancel_date') }}</p>
        </div>
        <div v-if="ma('lease_action') === 'keep'" class="md:col-span-2">
          <p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ ma('lease_keep_reason') }}</p>
        </div>
      </div>
    </div>

    <div class="pt-5 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Neu (neue Niederlassung)</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Ort (neu)</p><p class="ro-value">{{ mn('location') }}</p></div>
        <div><p class="ro-label">Firma (neu)</p><p class="ro-value">{{ mn('company') }}</p></div>
        <div>
          <p class="ro-label">Firma an Klingel sichtbar?</p>
          <p class="ro-value">{{ mn('sign_visible') }}</p>
          <p v-if="mn('sign_visible') === 'Nein'" class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">📌 Zettel anbringen</p>
        </div>
        <div><p class="ro-label">Wiedereröffnung</p><p class="ro-value">{{ mn('reopening') }}</p></div>
        <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ mn('cost_center') }}</p></div>
        <div><p class="ro-label">Startdatum</p><p class="ro-value">{{ mn('start_date') }}</p></div>
        <div class="md:col-span-2"><p class="ro-label">Adresse</p><p class="ro-value whitespace-pre-wrap">{{ mn('address') }}</p></div>
        <div><p class="ro-label">Vorgesetzter</p><p class="ro-value">{{ mn('location_supervisor_name') }}</p></div>
        <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ mn('contact_person_name') }}</p></div>
      </div>
    </div>
  </div>

  <!-- IT -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-6">
    <h2 class="text-base font-semibold text-[#3EAAB8]">IT</h2>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Alt</h3>
      <template v-if="ma('lease_action') === 'cancel'">
        <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-4 space-y-2">
          <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
          <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
            <span>{{ ia('confirm_dsl_cancel') ? '✅' : '⬜' }}</span>
            <div><strong>DSL/Internet gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_dsl_cancel') ? 'Ja' : 'Nein' }}</p></div>
          </div>
          <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
            <span>{{ ia('confirm_landline_cancel') ? '✅' : '⬜' }}</span>
            <div><strong>Festnetz gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_landline_cancel') ? 'Ja' : 'Nein' }}</p></div>
          </div>
        </div>
      </template>
      <p v-else class="text-sm text-gray-400 italic">Mietvertrag bleibt bestehen – keine IT-Abbauschritte erforderlich.</p>
    </div>

    <div class="pt-4 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
      <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">Neu</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div><p class="ro-label">Serverschrank vorhanden?</p><p class="ro-value">{{ inn('server_rack') }}</p></div>
        <div><p class="ro-label">Netzwerkverkabelung</p><p class="ro-value">{{ inn('network_cabling') }}</p></div>
        <div class="md:col-span-2"><p class="ro-label">DSL/Glasfaser-Dose installiert?</p><p class="ro-value">{{ inn('line_installed') }}</p></div>
        <template v-if="inn('line_installed') === 'Ja'">
          <div><p class="ro-label">Art / Anschluss</p><p class="ro-value">{{ inn('line_type') }}</p></div>
          <div class="md:col-span-2"><p class="ro-label">Standort</p><p class="ro-value whitespace-pre-wrap">{{ inn('line_location') }}</p></div>
        </template>
        <template v-if="inn('line_installed') === 'Nein'">
          <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
            📌 Vermieter wird mit der Installation beauftragt.
          </div>
          <div><p class="ro-label">Vermieter – Name</p><p class="ro-value">{{ inn('landlord_name') }}</p></div>
          <div><p class="ro-label">Vermieter – Kontakt</p><p class="ro-value">{{ inn('landlord_contact') }}</p></div>
        </template>
      </div>
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