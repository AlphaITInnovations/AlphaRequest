<script setup lang="ts">
import UserSelect from '@/components/UserSelect.vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useNiederlassungUmzug, Phase } from '@/composables/useNiederlassungUmzug'

const props = defineProps<{
  ctx: ReturnType<typeof useNiederlassungUmzug>
  phase: Phase
}>()

const { form, companies, submitting, fieldClass, isInvalid, validationTriggered } = props.ctx

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
          <div v-if="phase === 'edit'" class="mt-5">
            <UserSelect label="Verantwortlicher (Bearbeitung)"
                        :model-value="form.assignee"
                        @update:model-value="form.assignee = $event" />
          </div>
        </div>
      </aside>

      <!-- Main -->
      <section class="flex-1 space-y-6">

        <!-- ── Miete ── -->
        <div class="card space-y-8">
          <h2 class="section-title">Miete</h2>

          <!-- Alt -->
          <div class="space-y-4">
            <h3 class="subsection">Alt (bisherige Niederlassung)</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Ort (alt) *</label>
                <input v-model="form.miete_alt.location" :class="fieldClass('miete_alt.location')"
                       placeholder="z. B. Nürnberg Nord" />
              </div>
              <div>
                <label class="label">Firma (alt) *</label>
                <select v-model="form.miete_alt.company" :class="sc('miete_alt.company')">
                  <option value="">Bitte wählen</option>
                  <option v-for="c in companies" :key="c">{{ c }}</option>
                </select>
              </div>
              <div class="md:col-span-2">
                <label class="label">Mietvertrag (alt) *</label>
                <select v-model="form.miete_alt.lease_action" :class="sc('miete_alt.lease_action')">
                  <option value="">Bitte wählen</option>
                  <option value="cancel">Wird gekündigt</option>
                  <option value="keep">Bleibt bestehen</option>
                </select>
              </div>
              <div v-if="form.miete_alt.lease_action === 'cancel'">
                <label class="label">Kündigungsdatum *</label>
                <input type="date" v-model="form.miete_alt.lease_cancel_date"
                       :class="fieldClass('miete_alt.lease_cancel_date')" />
              </div>
              <div v-if="form.miete_alt.lease_action === 'keep'" class="md:col-span-2">
                <label class="label">Begründung *</label>
                <textarea v-model="form.miete_alt.lease_keep_reason"
                          :class="fieldClass('miete_alt.lease_keep_reason')"
                          rows="3" class="resize-none"
                          placeholder="z. B. andere Firma übernimmt die Fläche" />
              </div>
            </div>
          </div>

          <!-- Neu -->
          <div class="pt-6 border-t border-gray-100 dark:border-white/[0.06] space-y-4">
            <h3 class="subsection">Neu (neue Niederlassung)</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Ort der neuen Niederlassung *</label>
                <input v-model="form.miete_neu.location" :class="fieldClass('miete_neu.location')"
                       placeholder="z. B. Nürnberg Süd" />
              </div>
              <div>
                <label class="label">Firma der Niederlassung *</label>
                <select v-model="form.miete_neu.company" :class="sc('miete_neu.company')">
                  <option value="">Bitte wählen</option>
                  <option v-for="c in companies" :key="c">{{ c }}</option>
                </select>
              </div>
              <div>
                <label class="label">Firma an Klingel / Eingang sichtbar? *</label>
                <select v-model="form.miete_neu.sign_visible" :class="sc('miete_neu.sign_visible')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
                <p v-if="form.miete_neu.sign_visible === 'Nein'"
                   class="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  📌 Bitte Zettel an Klingel / Eingang anbringen.
                </p>
              </div>
              <div>
                <label class="label">Wiedereröffnung? *</label>
                <select v-model="form.miete_neu.reopening" :class="sc('miete_neu.reopening')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div :class="validationTriggered && isInvalid('miete_neu.location_supervisor_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
                <UserSelect
                  label="Vorgesetzter der Niederlassung *"
                  :model-value="form.miete_neu.location_supervisor_id ? { id: form.miete_neu.location_supervisor_id, name: form.miete_neu.location_supervisor_name } : null"
                  @update:model-value="v => { form.miete_neu.location_supervisor_id = v?.id ?? ''; form.miete_neu.location_supervisor_name = v?.name ?? '' }"
                />
              </div>
              <div :class="validationTriggered && isInvalid('miete_neu.contact_person_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
                <UserSelect
                  label="Ansprechpartner für Rückfragen *"
                  :model-value="form.miete_neu.contact_person_id ? { id: form.miete_neu.contact_person_id, name: form.miete_neu.contact_person_name } : null"
                  @update:model-value="v => { form.miete_neu.contact_person_id = v?.id ?? ''; form.miete_neu.contact_person_name = v?.name ?? '' }"
                />
              </div>
              <div>
                <label class="label">Kostenstelle *</label>
                <input v-model="form.miete_neu.cost_center"
                       @input="form.miete_neu.cost_center = form.miete_neu.cost_center.replace(/\D/g, '')"
                       :class="fieldClass('miete_neu.cost_center')" inputmode="numeric" />
              </div>
              <div>
                <label class="label">Startdatum *</label>
                <input type="date" v-model="form.miete_neu.start_date"
                       :class="fieldClass('miete_neu.start_date')" />
              </div>
              <div class="md:col-span-2">
                <label class="label">Adresse *</label>
                <textarea v-model="form.miete_neu.address" :class="fieldClass('miete_neu.address')"
                          rows="3" class="resize-none" />
              </div>
            </div>
          </div>
        </div>

        <!-- ── IT (nur edit) ── -->
        <template v-if="phase === 'edit'">
          <div class="card space-y-6">
            <h2 class="section-title">IT</h2>

            <!-- Alt -->
            <div class="space-y-4">
              <h3 class="subsection">Alt</h3>
              <template v-if="form.miete_alt.lease_action === 'cancel'">
                <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-5 space-y-3">
                  <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
                  <label class="flex items-start gap-3 cursor-pointer"
                         :class="validationTriggered && isInvalid('it_alt.confirm_dsl_cancel') ? 'ring-1 ring-red-500 rounded-lg p-1' : ''">
                    <input type="checkbox" v-model="form.it_alt.confirm_dsl_cancel"
                           class="mt-1 h-4 w-4 shrink-0 accent-[#3EAAB8]" />
                    <span class="text-sm text-red-800 dark:text-red-200 leading-snug">
                      <strong>Die DSL/Internetleitung wird gekündigt.</strong>
                    </span>
                  </label>
                  <label class="flex items-start gap-3 cursor-pointer"
                         :class="validationTriggered && isInvalid('it_alt.confirm_landline_cancel') ? 'ring-1 ring-red-500 rounded-lg p-1' : ''">
                    <input type="checkbox" v-model="form.it_alt.confirm_landline_cancel"
                           class="mt-1 h-4 w-4 shrink-0 accent-[#3EAAB8]" />
                    <span class="text-sm text-red-800 dark:text-red-200 leading-snug">
                      <strong>Die Festnetzrufnummer wird gekündigt und ist danach nicht mehr erreichbar!</strong>
                    </span>
                  </label>
                </div>
              </template>
            </div>

            <!-- Neu -->
            <div class="pt-4 border-t border-gray-100 dark:border-white/[0.06] space-y-4">
              <h3 class="subsection">Neu</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label class="label">Serverschrank vorhanden? *</label>
                  <select v-model="form.it_neu.server_rack" :class="sc('it_neu.server_rack')">
                    <option value="">–</option>
                    <option>Ja</option>
                    <option>Nein</option>
                  </select>
                </div>
                <div>
                  <label class="label">Netzwerkverkabelung *</label>
                  <input v-model="form.it_neu.network_cabling" :class="fieldClass('it_neu.network_cabling')"
                         placeholder="z. B. Cat6, Cat7" />
                </div>
                <div class="md:col-span-2">
                  <label class="label">DSL / Glasfaser-Dose vorhanden? *</label>
                  <select v-model="form.it_neu.line_installed" :class="sc('it_neu.line_installed')">
                    <option value="">–</option>
                    <option>Ja</option>
                    <option>Nein</option>
                  </select>
                </div>
                <template v-if="form.it_neu.line_installed === 'Ja'">
                  <div>
                    <label class="label">Art / Anschluss *</label>
                    <select v-model="form.it_neu.line_type" :class="sc('it_neu.line_type')">
                      <option value="">Bitte wählen</option>
                      <option>DSL</option>
                      <option>Glasfaser</option>
                    </select>
                  </div>
                  <div class="md:col-span-2">
                    <label class="label">Wo befindet sie sich? *</label>
                    <textarea v-model="form.it_neu.line_location"
                              :class="fieldClass('it_neu.line_location')"
                              rows="2" class="resize-none" />
                  </div>
                </template>
                <template v-if="form.it_neu.line_installed === 'Nein'">
                  <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20
                              px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                    📌 Vermieter wird mit der Installation beauftragt.
                  </div>
                  <div>
                    <label class="label">Vermieter – Name *</label>
                    <input v-model="form.it_neu.landlord_name" :class="fieldClass('it_neu.landlord_name')" />
                  </div>
                  <div>
                    <label class="label">Vermieter – Kontakt *</label>
                    <input v-model="form.it_neu.landlord_contact" :class="fieldClass('it_neu.landlord_contact')" />
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- ── Marketing ── -->
          <div class="card space-y-4">
            <h2 class="section-title">Marketing</h2>
            <div>
              <label class="label">Öffnungszeiten der Niederlassung *</label>
              <textarea v-model="form.marketing.opening_hours"
                        :class="fieldClass('marketing.opening_hours')"
                        rows="4" class="resize-none"
                        placeholder="z. B. Mo–Fr 08:00–17:00" />
            </div>
          </div>

          <!-- ── Fuhrpark ── -->
          <div class="card space-y-4">
            <h2 class="section-title">Fuhrpark</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Poolfahrzeuge benötigt? *</label>
                <select v-model="form.fuhrpark.pool_cars" :class="sc('fuhrpark.pool_cars')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div v-if="form.fuhrpark.pool_cars === 'Ja'">
                <label class="label">Benötigt ab *</label>
                <input type="date" v-model="form.fuhrpark.pool_cars_from"
                       :class="fieldClass('fuhrpark.pool_cars_from')" />
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
.subsection    { @apply text-sm font-semibold text-gray-600 dark:text-gray-400; }
.label         { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
</style>