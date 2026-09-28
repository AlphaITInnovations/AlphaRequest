<script setup lang="ts">
/**
 * Datei-Auswahl BEIM ANLEGEN eines Auftrags.
 *
 * Der Auftrag existiert noch nicht – es gibt also keine Ticket-ID, gegen die man
 * hochladen könnte. Deshalb werden die Dateien hier nur GEMERKT (im Speicher);
 * ProcessTicketCreateView lädt sie direkt nach dem Anlegen hoch und schaltet den
 * Auftrag dann weiter, damit sie in der Freigabe-Mail landen. Für bestehende
 * Aufträge übernimmt stattdessen ProcessAttachments (Upload direkt am Server).
 */
import { ref } from 'vue'

const props = withDefaults(defineProps<{ modelValue?: File[]; disabled?: boolean }>(), {
  modelValue: () => [], disabled: false,
})
const emit = defineEmits<{ 'update:modelValue': [files: File[]] }>()

const input = ref<HTMLInputElement | null>(null)

function pick() { if (!props.disabled) input.value?.click() }

function onChosen(ev: Event) {
  const el = ev.target as HTMLInputElement
  const chosen = Array.from(el.files ?? [])
  el.value = ''                     // sonst löst dieselbe Datei kein zweites Event aus
  if (chosen.length) emit('update:modelValue', [...props.modelValue, ...chosen])
}

function remove(i: number) {
  const next = props.modelValue.slice()
  next.splice(i, 1)
  emit('update:modelValue', next)
}

function human(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center gap-2">
      <button type="button" class="btn-secondary !py-1.5 !text-sm"
              :disabled="disabled" @click="pick">Datei auswählen</button>
      <span v-if="modelValue.length" class="text-xs text-gray-400">({{ modelValue.length }})</span>
    </div>
    <input ref="input" type="file" multiple class="hidden" @change="onChosen" />

    <ul v-if="modelValue.length"
        class="divide-y divide-gray-100 dark:divide-white/[0.06] rounded-xl
               border border-gray-200 dark:border-white/10 overflow-hidden">
      <li v-for="(f, i) in modelValue" :key="i"
          class="flex items-center gap-3 px-3 py-2 text-sm">
        <span class="truncate flex-1" :title="f.name">{{ f.name }}</span>
        <span class="text-xs text-gray-400 shrink-0">{{ human(f.size) }}</span>
        <button type="button" class="text-xs text-red-500 hover:underline shrink-0"
                :disabled="disabled" @click="remove(i)">Entfernen</button>
      </li>
    </ul>

    <p class="text-xs text-gray-400">
      Dateien werden beim Anlegen hochgeladen und der Freigabe-Mail beigefügt.
    </p>
  </div>
</template>
