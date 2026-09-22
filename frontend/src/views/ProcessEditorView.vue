<script setup lang="ts">
/**
 * Route-Einstieg des Prozess-Editors: wählt nur zwischen der klassischen und der
 * neuen (v2) Fassung. Beide teilen sich Zustandskern (useProcessEditor), API und
 * das ProcessDefinition-Format – umgeschaltet wird pro Browser über ein Flag
 * (useProcessEditorFlag), bis v2 die volle Parität erreicht und der klassische
 * Editor entfällt.
 */
import { useProcessEditorFlag } from '@/composables/useProcessEditorFlag'
import ProcessEditorLegacy from '@/components/process/editor/ProcessEditorLegacy.vue'
import ProcessEditorShell from '@/components/process/editor/v2/ProcessEditorShell.vue'

const { enabled } = useProcessEditorFlag()
</script>

<template>
  <ProcessEditorShell v-if="enabled" />
  <ProcessEditorLegacy v-else />
</template>
