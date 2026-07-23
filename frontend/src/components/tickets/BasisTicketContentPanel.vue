<script setup lang="ts">
import { computed } from 'vue'
import TicketSection from '@/components/tickets/TicketSection.vue'
import TicketField from '@/components/tickets/TicketField.vue'

export interface Eintrag {
  text:        string
  author_id:   string
  author_name: string
  timestamp:   string
}

// Einheitlich mit den übrigen ContentPanels: erhält das geparste description-JSON
// ({ ticket: { titel, eintraege } }).
const props = defineProps<{ description: any }>()

const titel     = computed<string>(() => props.description?.ticket?.titel ?? '')
const eintraege = computed<Eintrag[]>(() => props.description?.ticket?.eintraege ?? [])

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}
</script>

<template>
  <TicketSection title="Titel" variant="base">
    <TicketField label="Titel">{{ titel || '–' }}</TicketField>
  </TicketSection>

  <TicketSection title="Verlauf" variant="default">
    <div v-if="eintraege.length === 0" class="text-sm text-gray-400 italic py-4 text-center">
      Noch keine Einträge vorhanden.
    </div>

    <div v-for="(e, i) in eintraege" :key="i"
         class="relative pl-6 pb-5"
         :class="i < eintraege.length - 1 ? 'border-l-2 border-gray-200 dark:border-white/10' : 'border-l-2 border-transparent'">
      <div class="absolute -left-[5px] top-1 w-2.5 h-2.5 rounded-full"
           :class="i === eintraege.length - 1 ? 'bg-[#3EAAB8]' : 'bg-gray-300 dark:bg-gray-600'" />
      <div class="bg-gray-50 dark:bg-[#1A2130] rounded-xl border border-gray-200/80 dark:border-white/[0.06] p-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-medium text-gray-900 dark:text-white">{{ e.author_name }}</span>
          <span class="text-xs text-gray-400">{{ formatDate(e.timestamp) }}</span>
        </div>
        <p class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ e.text }}</p>
      </div>
    </div>
  </TicketSection>
</template>
