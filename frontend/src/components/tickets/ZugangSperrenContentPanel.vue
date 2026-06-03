<script setup lang="ts">
const props = defineProps<{ description: any }>()

const p  = (k: string) => props.description?.personal?.[k] ?? '—'
const it = (k: string) => props.description?.it?.[k]       ?? '—'
const f  = (k: string) => props.description?.fuhrpark?.[k] ?? '—'
</script>

<template>
  <!-- Basisdaten -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Basisdaten</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Vorname</p><p class="ro-value">{{ p('first_name') }}</p></div>
      <div><p class="ro-label">Nachname</p><p class="ro-value">{{ p('last_name') }}</p></div>
      <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ p('cost_center') }}</p></div>
      <div><p class="ro-label">Firma lt. Arbeitsvertrag</p><p class="ro-value">{{ p('contract_company') }}</p></div>
      <div><p class="ro-label">Austrittsdatum</p><p class="ro-value">{{ p('exit_date') }}</p></div>
      <div><p class="ro-label">Abfindungsvereinbarung</p><p class="ro-value">{{ p('severance_agreement') }}</p></div>
    </div>
  </div>

  <!-- IT -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-5">
    <h2 class="text-base font-semibold text-[#3EAAB8]">IT</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <p class="ro-label">Mailweiterleitung?</p>
        <p class="ro-value">{{ it('mail_forwarding') }}</p>
      </div>
      <div>
        <p class="ro-label">Weiterleiten an</p>
        <p class="ro-value">{{ it('mail_forwarding') === 'Ja' ? it('mail_forward_to') : '—' }}</p>
      </div>
      <div>
        <p class="ro-label">Postfachzugriff gewähren?</p>
        <p class="ro-value">{{ it('mailbox_access') }}</p>
      </div>
      <div class="md:col-span-2">
        <p class="ro-label">Zugriff für</p>
        <p class="ro-value whitespace-pre-wrap">{{ it('mailbox_access') === 'Ja' ? it('mailbox_access_for') : '—' }}</p>
      </div>
      <div>
        <p class="ro-label">Abwesenheitsnotiz?</p>
        <p class="ro-value">{{ it('auto_reply') }}</p>
      </div>
      <div class="md:col-span-2">
        <p class="ro-label">Text der Abwesenheitsnotiz</p>
        <p class="ro-value whitespace-pre-wrap font-mono text-xs">{{ it('auto_reply') === 'Ja' ? it('auto_reply_text') : '—' }}</p>
      </div>
    </div>

    <div class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
      <p class="font-semibold mb-1">📌 Wichtige Hinweise</p>
      <ul class="list-disc pl-4 space-y-1">
        <li><strong>Mailweiterleitung</strong> und <strong>Postfachzugriff</strong> sind jeweils <strong>maximal 30 Tage</strong> möglich.</li>
        <li>Postfächer werden gesichert – <strong>neue E-Mails werden nicht mehr zugestellt.</strong></li>
        <li>Abwesenheitsnotiz ggf. Platzhalter prüfen: <code>&lt;Name&gt;</code>, <code>&lt;Ersatzmailadresse&gt;</code></li>
      </ul>
    </div>
  </div>

  <!-- Fuhrpark -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Fuhrpark</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Dienstwagen vorhanden?</p><p class="ro-value">{{ f('car') }}</p></div>
      <div><p class="ro-label">Rückgabedatum</p><p class="ro-value">{{ f('car') === 'Ja' ? f('car_return_date') : '—' }}</p></div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>