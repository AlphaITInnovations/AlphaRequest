<script setup lang="ts">
/**
 * Dokument-Phase (view='document'): je konfiguriertem Dokument eine Karte.
 *
 * Die für die Dokument-Phase zuständige Stelle (bzw. Admin) sieht je Dokument
 * „Ausfüllen & exportieren" (öffnet den Editor mit Server-Vorschau + Word/PDF-
 * Export); Beobachter:innen/Beteiligte sehen nur den Hinweis, dass das Dokument
 * erstellt wird. Vorlagen-Format (Word .docx ODER PDF-Formular) und Füllung
 * liegen serverseitig – der Client wählt nur AUS, welches Dokument.
 */
import { computed, ref } from 'vue'
import type { OptionSources, PhaseDef, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import DocumentEditorModal from '@/components/process/form/DocumentEditorModal.vue'

const props = defineProps<{
  definition: ProcessDefinition
  ticket: ProcessTicketOut
  phase: PhaseDef
  sources?: OptionSources
  /** Leseansicht (kein Bearbeiten) – der Export bleibt für Berechtigte erlaubt. */
  readonly?: boolean
}>()

/** Erzeugen darf NUR die für die Phase zuständige Stelle (bzw. Admin) – das
 *  Backend liefert das als Ability. Alle anderen sehen nur einen Hinweis. */
const darfErzeugen = computed(() => props.ticket.abilities?.export_document === true)

/** document.key des gerade offenen Editor-Modals (null = keins offen). */
const openDoc = ref<string | null>(null)
</script>

<template>
  <section class="card-section space-y-3">
    <h3 class="section-title mb-0">Dokumente</h3>

    <div v-for="doc in phase.documents" :key="doc.key"
         class="rounded-xl border border-gray-200 dark:border-white/10 px-4 py-3
                flex items-center justify-between gap-3 flex-wrap">
      <div class="min-w-0">
        <p class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
          {{ doc.title || 'Dokument' }}
        </p>
        <p v-if="!darfErzeugen" class="text-xs text-gray-500 dark:text-gray-400">
          Wird von der zuständigen Stelle erstellt. Sobald der Auftrag weitergeht,
          werden Sie – sofern Sie beteiligt sind – benachrichtigt.
        </p>
        <p v-else class="text-xs text-gray-400">
          Vorschau ausfüllen und als Word oder PDF exportieren.
        </p>
      </div>
      <button v-if="darfErzeugen" type="button" @click="openDoc = doc.key"
              class="px-3 py-1.5 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#2B7D89]
                     transition shrink-0">
        Ausfüllen &amp; exportieren
      </button>
    </div>

    <DocumentEditorModal v-if="openDoc" :ticket-id="ticket.id" :document-key="openDoc"
                         @close="openDoc = null" />
  </section>
</template>
