<script setup lang="ts">
/**
 * Route-Einstieg des Prozess-Editors. Seit dem Cutover gibt es nur noch eine
 * Fassung (früher „v2"): die Shell mit horizontalen Tabs. Zustandskern
 * (useProcessEditor), API und ProcessDefinition-Format unverändert.
 */
import ProcessEditorShell from '@/components/process/editor/v2/ProcessEditorShell.vue'
</script>

<template>
  <ProcessEditorShell />
</template>
