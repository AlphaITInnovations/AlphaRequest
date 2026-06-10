<script setup lang="ts">
import { ref } from 'vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import BasisTicketContentPanel from '@/components/tickets/BasisTicketContentPanel.vue'
import type { useBasisTicket } from '@/composables/useBasisTicket'

const props = defineProps<{
  ctx: ReturnType<typeof useBasisTicket>
}>()

const { form, phase, fieldClass, isInvalid, validationTriggered } = props.ctx

// Beschreibung für Create-Phase
const createBeschreibung = ref('')

function handleCreate() {
  props.ctx.submitCreate(createBeschreibung.value)
}
</script>

<template>
  <div class="max-w-7xl mx-auto">

    <!-- Error Bar -->
    <div v-if="validationTriggered && ctx.errors.value?.length"
         class="mb-6 rounded-xl border border-red-300 bg-red-50 dark:bg-red-900/20
                dark:border-red-500/30 px-4 py-3 text-red-800 dark:text-red-300">
      <p class="font-semibold">Bitte alle Pflichtfelder ausfüllen.</p>
      <p class="text-sm mt-0.5">{{ ctx.errors.value.length }} Fehler gefunden.</p>
    </div>

    <div class="flex flex-col lg:flex-row gap-6">

      <!-- ── Sidebar: Details ── -->
      <aside class="w-full lg:w-[320px] flex-shrink-0">
        <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-6 lg:sticky lg:top-4">
          <TicketDetails
            :phase="phase"
            :priority="form.priority"
            :comment="form.comment"
            :accountable="form.accountable"
            :accountable-error="validationTriggered && isInvalid('accountable')"
            @update:priority="form.priority = $event"
            @update:comment="form.comment = $event"
            @update:accountable="form.accountable = $event"
          />
        </div>
      </aside>

      <!-- ── Main ── -->
      <section class="flex-1 space-y-6">

        <!-- ═══ Create ═══ -->
        <template v-if="phase === 'create'">
          <div class="card">
            <label class="label">Titel *</label>
            <input v-model="form.ticket.titel"
                   :class="fieldClass('ticket.titel')"
                   placeholder="Kurze Beschreibung des Anliegens…" />
          </div>

          <div class="card">
            <label class="label">Beschreibung *</label>
            <textarea v-model="createBeschreibung"
                      class="w-full rounded-xl border px-3.5 py-2.5 text-sm transition
                             focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50
                             bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                             placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                      :class="validationTriggered && !createBeschreibung.trim() && ctx.errors.value.includes('ticket.beschreibung')
                        ? 'border-red-400 bg-red-50 dark:bg-red-900/20'
                        : 'border-gray-200 dark:border-white/10'"
                      rows="6"
                      placeholder="Beschreibe dein Anliegen ausführlich…" />
            <p v-if="validationTriggered && !createBeschreibung.trim() && ctx.errors.value.includes('ticket.beschreibung')"
               class="text-xs text-red-500 mt-1">Pflichtfeld</p>
          </div>
        </template>

        <!-- ═══ Edit ═══ -->
        <template v-if="phase === 'edit'">
          <!-- ContentPanel: Titel + Verlauf (readonly) -->
          <BasisTicketContentPanel :description="{ ticket: form.ticket }" />

          <!-- Neuer Eintrag -->
          <div class="card">
            <h2 class="text-lg font-semibold text-[#3EAAB8] mb-3">Neuer Eintrag</h2>
            <textarea v-model="ctx.newEntryText.value"
                      class="w-full rounded-xl border border-gray-200 dark:border-white/10
                             px-3.5 py-2.5 text-sm transition
                             focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50
                             bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                             placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                      rows="5"
                      placeholder="Ergänzende Informationen, Rückfragen, Statusupdates…" />
            <p class="text-xs text-gray-400 mt-1.5">
              Wird beim Speichern automatisch mit deinem Namen und Zeitstempel hinterlegt.
            </p>
          </div>
        </template>

      </section>
    </div>

    <!-- Action Bar -->
    <TicketActionBar
      :phase="phase"
      :loading="ctx.submitting.value"
      :confirm-create-open="ctx.pendingConfirm.value"
      :confirm-complete-open="ctx.pendingComplete.value"
      @create="handleCreate"
      @create-confirmed="ctx.confirmCreate()"
      @create-cancelled="ctx.pendingConfirm.value = false"
      @save="ctx.submitEdit('save')"
      @complete="ctx.submitEdit('complete')"
      @complete-confirmed="ctx.confirmComplete()"
      @complete-cancelled="ctx.pendingComplete.value = false"
    />
  </div>
</template>

<style scoped>
@reference "../../style.css";
.label { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
.card { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6; }
</style>