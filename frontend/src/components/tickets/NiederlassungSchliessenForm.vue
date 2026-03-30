<script setup lang="ts">
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useNiederlassungSchliessen, Phase } from '@/composables/useNiederlassungSchliessen'

const props = defineProps<{
  ctx: ReturnType<typeof useNiederlassungSchliessen>
  phase: Phase
}>()

const { form, submitting, fieldClass, isInvalid, validationTriggered } = props.ctx

const sc = (path: string) =>
  fieldClass(path).replace('placeholder-gray-400 dark:placeholder-gray-500', '')
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

      <!-- Sidebar -->
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

      <!-- Main -->
      <section class="flex-1 space-y-6">

        <!-- ── Personalabteilung (Phase 1 + 2) ── -->
        <div class="card space-y-4">
          <h2 class="section-title">Personalabteilung</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Welche Niederlassung betrifft es? *</label>
              <input v-model="form.personal.location" :class="fieldClass('personal.location')"
                     placeholder="z. B. Nürnberg Nord" />
            </div>
            <div>
              <label class="label">Schließungsdatum *</label>
              <input type="date" v-model="form.personal.closing_date"
                     :class="fieldClass('personal.closing_date')" />
            </div>
            <div class="md:col-span-2">
              <label class="label">Adresse der Niederlassung *</label>
              <textarea v-model="form.personal.address" :class="fieldClass('personal.address')"
                        rows="3" class="resize-none" placeholder="Straße, PLZ Ort" />
            </div>
          </div>
        </div>

        <!-- ── IT (nur edit) ── -->
        <template v-if="phase === 'edit'">
          <div class="card space-y-6">
            <h2 class="section-title">IT</h2>

            <!-- Wichtige Hinweise / Checkboxen -->
            <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-5 space-y-3">
              <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
              <label class="flex items-start gap-3 cursor-pointer"
                     :class="validationTriggered && isInvalid('it.confirm_dsl_cancel') ? 'ring-1 ring-red-400 rounded-lg p-1' : ''">
                <input type="checkbox" v-model="form.it.confirm_dsl_cancel"
                       class="mt-1 h-4 w-4 shrink-0 accent-[#3EAAB8]" />
                <span class="text-sm text-red-800 dark:text-red-200 leading-snug">
                  <strong>Die DSL/Internetleitung wird gekündigt.</strong>
                </span>
              </label>
              <label class="flex items-start gap-3 cursor-pointer"
                     :class="validationTriggered && isInvalid('it.confirm_landline_cancel') ? 'ring-1 ring-red-400 rounded-lg p-1' : ''">
                <input type="checkbox" v-model="form.it.confirm_landline_cancel"
                       class="mt-1 h-4 w-4 shrink-0 accent-[#3EAAB8]" />
                <span class="text-sm text-red-800 dark:text-red-200 leading-snug">
                  <strong>Die Festnetzrufnummer wird gekündigt und ist danach nicht mehr erreichbar!</strong>
                </span>
              </label>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="md:col-span-2">
                <label class="label">Was geschieht mit der Hardware vor Ort? *</label>
                <select v-model="form.it.hardware_action" :class="sc('it.hardware_action')">
                  <option value="">Bitte wählen</option>
                  <option value="return_it">Wird an die IT gesendet</option>
                  <option value="transfer_branch">Wird in eine andere Niederlassung transferiert</option>
                </select>
              </div>
              <div v-if="form.it.hardware_action === 'transfer_branch'" class="md:col-span-2">
                <label class="label">Welche Niederlassung? *</label>
                <textarea v-model="form.it.transfer_target" :class="fieldClass('it.transfer_target')"
                          rows="2" class="resize-none" placeholder="Adresse der Ziel-Niederlassung" />
              </div>
            </div>
          </div>

          <!-- ── Fuhrpark ── -->
          <div class="card space-y-4">
            <h2 class="section-title">Fuhrpark</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Poolfahrzeuge vor Ort? *</label>
                <select v-model="form.fuhrpark.pool_cars" :class="sc('fuhrpark.pool_cars')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div v-if="form.fuhrpark.pool_cars === 'Ja'">
                <label class="label">Rückgabedatum *</label>
                <input type="date" v-model="form.fuhrpark.return_date"
                       :class="fieldClass('fuhrpark.return_date')" />
              </div>
            </div>
          </div>
        </template>

      </section>
    </div>

    <TicketActionBar
      :phase="phase"
      :loading="submitting"
      :confirm-create-open="ctx.pendingConfirm.value"
      :confirm-complete-open="ctx.pendingComplete.value"
      @create="ctx.submitCreate()"
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
.card          { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6; }
.section-title { @apply text-lg font-semibold text-[#3EAAB8]; }
.label         { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
</style>