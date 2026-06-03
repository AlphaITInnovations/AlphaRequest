<script setup lang="ts">
const props = defineProps<{ description: any }>()

const h = (k: string) => props.description?.hardware?.[k] ?? '—'
const m = ()          => props.description?.hardware?.monitor ?? {}
const a = ()          => props.description?.hardware?.artikel ?? {}
</script>

<template>
  <!-- Basisdaten -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Basisdaten</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Mitarbeitertyp</p><p class="ro-value">{{ h('mitarbeiterTyp') }}</p></div>
      <div><p class="ro-label">Vorname</p><p class="ro-value">{{ h('vorname') }}</p></div>
      <div><p class="ro-label">Nachname</p><p class="ro-value">{{ h('nachname') }}</p></div>
      <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ h('kostenstelle') }}</p></div>
      <div><p class="ro-label">Firma</p><p class="ro-value">{{ h('firma') }}</p></div>
      <div class="md:col-span-2">
        <p class="ro-label">Lieferadresse</p>
        <p class="ro-value whitespace-pre-wrap">{{ h('addr_strasse') }} {{ h('addr_nr') }}, {{ h('addr_plz') }} {{ h('addr_stadt') }}<template v-if="h('addr_tuerschild') !== '—'"><br>(Türschild: {{ h('addr_tuerschild') }})</template></p>
      </div>
      <div><p class="ro-label">Lieferung bis</p><p class="ro-value">{{ h('lieferungBis') }}</p></div>
    </div>
  </div>

  <!-- Hardware -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Hardware</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div><p class="ro-label">Gerätetyp</p><p class="ro-value">{{ h('geraet') }}</p></div>
      <div>
        <p class="ro-label">Monitor</p>
        <p class="ro-value">{{ m().benoetigt ? `Ja (${m().anzahl}×)` : 'Nein' }}</p>
      </div>
      <div>
        <p class="ro-label">Dockingstation bestellen</p>
        <p class="ro-value">{{ a().Dockingstation ? 'Ja' : 'Nein' }}</p>
      </div>
      <div>
        <p class="ro-label">Dockingstation vorhanden</p>
        <p class="ro-value">{{ h('dockingVorhanden') === true || h('dockingVorhanden') === 'true' ? 'Ja' : 'Nein' }}</p>
      </div>
      <div class="md:col-span-2">
        <p class="ro-label">Zusätzliche Hardware</p>
        <p class="ro-value">
          {{
            [
              a().Notebook        && 'Notebook',
              a().MiniPC          && 'Mini-PC',
              a().MausUndTastatur && 'Maus & Tastatur',
              a().Headset         && 'Headset',
              a().Webcam          && 'Webcam',
              a().Handy           && 'Handy',
              a().SIM             && 'SIM-Karte',
            ].filter(Boolean).join(', ') || '—'
          }}
        </p>
      </div>
    </div>
  </div>

  <!-- Zusatzinfos -->
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6 space-y-4">
    <h2 class="text-base font-semibold text-[#3EAAB8]">Zusatzinformationen</h2>
    <div>
      <p class="ro-label">Grund der Neubestellung</p>
      <p class="ro-value whitespace-pre-wrap">{{ h('grundBestellung') }}</p>
    </div>
    <div>
      <p class="ro-label">Bemerkung</p>
      <p class="ro-value whitespace-pre-wrap">{{ h('bemerkung') }}</p>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>