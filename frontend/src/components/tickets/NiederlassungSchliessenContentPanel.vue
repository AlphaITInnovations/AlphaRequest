<script setup lang="ts">
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
  <!-- Personalabteilung -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Personalabteilung</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ p('location') }}</p></div>
      <div><p class="ro-label">Schließungsdatum</p><p class="ro-value">{{ p('closing_date') }}</p></div>
      <div class="md:col-span-2"><p class="ro-label">Adresse</p><p class="ro-value whitespace-pre-wrap">{{ p('address') }}</p></div>
    </div>
  </div>

  <!-- IT -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-5">
    <h2 class="text-base font-semibold text-[#3EAAB8]">IT</h2>

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

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="md:col-span-2">
        <p class="ro-label">Umgang mit Hardware</p>
        <p class="ro-value">{{ HARDWARE_LABEL[it('hardware_action')] ?? it('hardware_action') }}</p>
      </div>
      <div v-if="it('hardware_action') === 'transfer_branch'" class="md:col-span-2">
        <p class="ro-label">Ziel-Niederlassung</p>
        <p class="ro-value whitespace-pre-wrap">{{ it('transfer_target') }}</p>
      </div>
    </div>
  </div>

  <!-- Fuhrpark -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Fuhrpark</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Poolfahrzeuge vor Ort?</p><p class="ro-value">{{ f('pool_cars') }}</p></div>
      <div v-if="f('pool_cars') === 'Ja'"><p class="ro-label">Rückgabedatum</p><p class="ro-value">{{ f('return_date') }}</p></div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>