<script setup lang="ts">
/**
 * Auswahl genau einer Fachabteilung (Wert = Gruppen-ID).
 *
 * Wichtig: Eine Definition kann eine Gruppe referenzieren, die es nicht mehr
 * gibt (gelöscht, anderer Mandant, Import). Ein <select> ohne passende <option>
 * würde den Wert beim ersten Rendern still verlieren – deshalb wird ein
 * unbekannter Wert als rote Option mitgeführt.
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string | null
  groups: { id: string; name: string }[]
  placeholder?: string
  allowEmpty?: boolean
}>(), {
  placeholder: '— bitte wählen —',
  allowEmpty: true,
})

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

const list = computed(() => props.groups ?? [])

const isUnknown = computed(() =>
  !!props.modelValue && !list.value.some((g) => g.id === props.modelValue))

function onChange(e: Event) {
  const v = (e.target as HTMLSelectElement).value
  emit('update:modelValue', v === '' ? null : v)
}
</script>

<template>
  <select :value="modelValue ?? ''" @change="onChange"
          class="pfi" :class="isUnknown ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''">
    <!-- Bei allowEmpty=false bleibt der Platzhalter sichtbar, aber nicht wählbar. -->
    <option value="" :disabled="!allowEmpty">{{ placeholder }}</option>
    <option v-for="g in list" :key="g.id" :value="g.id">{{ g.name }}</option>
    <option v-if="isUnknown" :value="modelValue" class="text-red-600">
      Unbekannt: {{ modelValue }}
    </option>
  </select>
</template>

<style scoped>
@reference "../../../style.css";
.pfi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
