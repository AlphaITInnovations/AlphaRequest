<script setup lang="ts">
/**
 * „Newsfeed" – hier erscheinen künftig Update-Beschreibungen, neue Funktionen
 * und sonstige Neuigkeiten.
 *
 * NOCH Platzhalter: die eigentliche Umsetzung (Einträge pflegen/anzeigen) folgt.
 * Die Seite existiert bereits, damit der Navigationspunkt und die Route stehen.
 */
import AppLayout from '@/components/AppLayout.vue'
</script>

<template>
  <AppLayout title="Newsfeed">
    <div class="max-w-2xl mx-auto">
      <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">Newsfeed</h1>

      <!-- Platzhalter bis zur echten Umsetzung -->
      <div class="mt-8 flex flex-col items-center justify-center text-center gap-4
                  rounded-2xl border border-dashed border-gray-200 dark:border-white/10
                  bg-gray-50/60 dark:bg-white/[0.02] px-6 py-16">
        <div class="w-14 h-14 rounded-2xl bg-[#3EAAB8]/10 flex items-center justify-center">
          <svg class="w-7 h-7 text-[#3EAAB8]" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/>
            <path d="M18 14h-8M15 18h-5M10 6h8v4h-8V6Z"/>
          </svg>
        </div>
        <div class="space-y-1.5">
          <p class="text-base font-medium text-gray-700 dark:text-gray-200">
            Hier wird es in Zukunft Neuigkeiten geben.
          </p>
          <p class="text-sm text-gray-500 dark:text-gray-400 max-w-md">
            An dieser Stelle erscheinen künftig Update-Beschreibungen, neue Funktionen
            und weitere Informationen rund um AlphaRequest.
          </p>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
