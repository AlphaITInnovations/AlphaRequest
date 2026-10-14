<script setup lang="ts">
/**
 * „Allgemeine Hinweise" – statische Informationsseite, erreichbar über einen
 * kleinen Link unten in der Navigation. Reiner Text (sprachliche Hinweise /
 * allgemeine Informationen), keine Daten, kein Rechte-Gate über die normale
 * Anmeldung hinaus.
 */
import AppLayout from '@/components/AppLayout.vue'
</script>

<template>
  <AppLayout title="Allgemeine Hinweise">
    <div class="max-w-2xl mx-auto space-y-8">
      <h1 class="text-2xl font-semibold text-gray-900 dark:text-white">Allgemeine Hinweise</h1>

      <section class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Sprachliche Hinweise</h2>
        <p class="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
          Aus Gründen der besseren Lesbarkeit werden in diesem System teilweise die Anreden
          „Herr“ und „Frau“ sowie geschlechtsspezifische Personenbezeichnungen verwendet.
          Diese sind, sofern nicht ausdrücklich anders angegeben, geschlechtsneutral zu
          verstehen und beziehen sich gleichermaßen auf alle Geschlechter.
        </p>
      </section>

      <section class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Allgemeine Informationen</h2>
        <p class="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
          Die in diesem System verwendeten Bezeichnungen und Begriffe dienen der einheitlichen
          Darstellung und vereinfachten Bearbeitung von Aufträgen.
        </p>
      </section>
    </div>
  </AppLayout>
</template>
