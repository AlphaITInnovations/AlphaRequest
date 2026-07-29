<script setup lang="ts">
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import TicketSection from '@/components/tickets/TicketSection.vue'
import EinstellungContentPanel from '@/components/tickets/EinstellungContentPanel.vue'
import type { useEinstellung, Phase } from '@/composables/useEinstellung'

const props = defineProps<{
  ctx: ReturnType<typeof useEinstellung>
  phase: Phase
}>()

const {
  form, companies, submitting, fieldClass, validationTriggered, stage,
} = props.ctx

const selectClass = (path: string) =>
  fieldClass(path).replace('focus:ring-2', '').replace('placeholder-gray-400 dark:placeholder-gray-500', '')
</script>

<template>
  <div class="max-w-7xl mx-auto">

    <!-- ═══════════════════════ ERSTELLUNG (editierbar) ═══════════════════════ -->
    <template v-if="phase === 'create' || stage === 'erstellung'">
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
              :accountable="null"
              :accountable-locked="true"
              accountable-locked-hint="Wird automatisch Herrn Lutz zur Freigabe vorgelegt."
              @update:priority="form.priority = $event"
              @update:comment="form.comment = $event"
            />
          </div>
        </aside>

        <!-- Felder -->
        <section class="flex-1 space-y-6">
          <TicketSection title="Basisdaten" variant="base">
            <p class="text-sm text-gray-500 dark:text-gray-400 -mt-1">
              Einstellungsdaten der/des neuen Mitarbeitenden. Nach der Freigabe erstellt das Sekretariat GL den Arbeitsvertrag.
            </p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Anrede *</label>
                <select v-model="form.base.salutation" :class="selectClass('base.salutation')">
                  <option value="">Bitte wählen</option>
                  <option>Herr</option><option>Frau</option><option>Divers</option>
                </select>
              </div>
              <div>
                <label class="label">Vorname *</label>
                <input v-model="form.base.first_name" :class="fieldClass('base.first_name')" placeholder="Max" />
              </div>
              <div>
                <label class="label">Nachname *</label>
                <input v-model="form.base.last_name" :class="fieldClass('base.last_name')" placeholder="Mustermann" />
              </div>
              <div>
                <label class="label">Titel *</label>
                <input v-model="form.base.title" :class="fieldClass('base.title')" placeholder="z. B. Niederlassungsleiter" />
              </div>
              <div>
                <label class="label">Firma lt. Arbeitsvertrag *</label>
                <select v-model="form.base.contract_company" :class="selectClass('base.contract_company')">
                  <option value="">Bitte wählen</option>
                  <option v-for="c in companies" :key="c">{{ c }}</option>
                </select>
              </div>
              <div>
                <label class="label">Niederlassung *</label>
                <input v-model="form.base.location" :class="fieldClass('base.location')" />
              </div>
              <div>
                <label class="label">Kostenstelle *</label>
                <input v-model="form.base.cost_center"
                       @input="form.base.cost_center = form.base.cost_center.replace(/\D/g, '')"
                       :class="fieldClass('base.cost_center')" inputmode="numeric" />
              </div>
              <div>
                <label class="label">Arbeitsbeginn (laut Vertrag) *</label>
                <input type="date" v-model="form.base.start_date" :class="fieldClass('base.start_date')" />
              </div>
            </div>
          </TicketSection>

          <TicketSection title="Gehalt & Konditionen" variant="hr" badge="Sekretariat GL">
            <p class="text-sm text-gray-500 dark:text-gray-400 -mt-1">
              Vertraulich – nur für Sekretariat GL sichtbar.
            </p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Gehalt</label>
                <input v-model="form.personal.salary" :class="fieldClass('personal.salary')"
                       placeholder="z. B. 3.500 € / Monat" />
              </div>
              <div class="md:col-span-2">
                <label class="label">Konditionen</label>
                <textarea v-model="form.personal.conditions" rows="3" class="resize-none"
                          :class="fieldClass('personal.conditions')"
                          placeholder="z. B. 13. Gehalt, 30 Tage Urlaub, Probezeit …" />
              </div>
            </div>
          </TicketSection>
        </section>
      </div>

      <TicketActionBar
        :phase="phase"
        :loading="submitting"
        :confirm-create-open="ctx.pendingConfirm.value"
        @create="ctx.submitCreate()"
        @create-confirmed="ctx.confirmCreate()"
        @create-cancelled="ctx.pendingConfirm.value = false"
      />
    </template>

    <!-- ═══════════ VERTRAG / VERTRAGSRÜCKLAUF (read-only + Aktion) ═══════════ -->
    <template v-else>
      <div class="rounded-2xl border border-[#3EAAB8]/40 bg-[#3EAAB8]/5 px-4 py-3 mb-6 text-sm text-gray-700 dark:text-gray-200">
        <template v-if="stage === 'vertrag'">
          Bitte den <strong>Arbeitsvertrag erstellen und versenden</strong>. Anschließend „{{ ctx.completeLabel.value }}".
        </template>
        <template v-else>
          Sobald der <strong>unterschriebene Arbeitsvertrag</strong> zurück ist: „{{ ctx.completeLabel.value }}" –
          dadurch wird automatisch der Onboarding-Folgeprozess gestartet.
        </template>
      </div>

      <div class="space-y-6">
        <EinstellungContentPanel :description="ctx.descPreview.value" />
      </div>

      <TicketActionBar
        phase="edit"
        :loading="submitting"
        :complete-label="ctx.completeLabel.value"
        :confirm-complete-open="ctx.pendingComplete.value"
        @save="ctx.submitEdit('save')"
        @complete="ctx.submitEdit('complete')"
        @complete-confirmed="ctx.confirmComplete()"
        @complete-cancelled="ctx.pendingComplete.value = false"
      />
    </template>
  </div>
</template>
