<script setup lang="ts">
import UserSelect from '@/components/UserSelect.vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useNiederlassungAnmelden, Phase } from '@/composables/useNiederlassungAnmelden'

const props = defineProps<{
  ctx: ReturnType<typeof useNiederlassungAnmelden>
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
        </div>
      </aside>

      <!-- Main -->
      <section class="flex-1 space-y-6">

        <!-- ── Niederlassung (Phase 1 + 2) ── -->
        <div class="card space-y-6">
          <h2 class="section-title">Miete / Niederlassung</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

            <div>
              <label class="label">Ort der Niederlassung *</label>
              <input v-model="form.miete.location" :class="fieldClass('miete.location')" />
            </div>
            <div>
              <label class="label">Firma der Niederlassung *</label>
              <select v-model="form.miete.company" :class="sc('miete.company')">
                <option value="">Bitte wählen</option>
                <option v-for="c in companies" :key="c">{{ c }}</option>
              </select>
            </div>
            <div>
              <label class="label">Wiedereröffnung? *</label>
              <select v-model="form.miete.reopening" :class="sc('miete.reopening')">
                <option value="">–</option>
                <option>Ja</option>
                <option>Nein</option>
              </select>
            </div>
            <div>
              <label class="label">Firma an Klingel / Eingang sichtbar? *</label>
              <select v-model="form.miete.sign_visible" :class="sc('miete.sign_visible')">
                <option value="">–</option>
                <option>Ja</option>
                <option>Nein</option>
              </select>
              <p v-if="form.miete.sign_visible === 'Nein'"
                 class="mt-1 text-xs text-amber-700 dark:text-amber-400">
                📌 Bitte Zettel oder ähnliches an Klingel / Eingang anbringen.
              </p>
            </div>

            <div :class="validationTriggered && isInvalid('miete.location_supervisor_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
              <UserSelect
                label="Vorgesetzter der Niederlassung *"
                :model-value="form.miete.location_supervisor_id ? { id: form.miete.location_supervisor_id, name: form.miete.location_supervisor_name } : null"
                @update:model-value="v => { form.miete.location_supervisor_id = v?.id ?? ''; form.miete.location_supervisor_name = v?.name ?? '' }"
              />
            </div>
            <div :class="validationTriggered && isInvalid('miete.contact_person_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
              <UserSelect
                label="Ansprechpartner für Rückfragen *"
                :model-value="form.miete.contact_person_id ? { id: form.miete.contact_person_id, name: form.miete.contact_person_name } : null"
                @update:model-value="v => { form.miete.contact_person_id = v?.id ?? ''; form.miete.contact_person_name = v?.name ?? '' }"
              />
            </div>

            <div>
              <label class="label">Kostenstelle *</label>
              <input v-model="form.miete.cost_center"
                     @input="form.miete.cost_center = form.miete.cost_center.replace(/\D/g, '')"
                     :class="fieldClass('miete.cost_center')" inputmode="numeric" />
            </div>
            <div>
              <label class="label">Startdatum *</label>
              <input type="date" v-model="form.miete.start_date" :class="fieldClass('miete.start_date')" />
            </div>
            <div class="md:col-span-2">
              <label class="label">Adresse *</label>
              <textarea v-model="form.miete.address" :class="fieldClass('miete.address')"
                        rows="3" class="resize-none" />
            </div>
          </div>
        </div>

        <!-- ── IT (nur edit) ── -->
        <template v-if="phase === 'edit'">
          <div class="card space-y-6">
            <h2 class="section-title">IT</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

              <div>
                <label class="label">Serverschrank vorhanden? *</label>
                <select v-model="form.it.server_rack" :class="sc('it.server_rack')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div>
                <label class="label">Netzwerkverkabelung *</label>
                <input v-model="form.it.network_cabling" :class="fieldClass('it.network_cabling')"
                       placeholder="z. B. Cat 6, Cat 7" />
              </div>
              <div class="md:col-span-2">
                <label class="label">DSL- oder Glasfaser-Dose installiert? *</label>
                <select v-model="form.it.line_installed" :class="sc('it.line_installed')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>

              <!-- Ja → Anschlussdetails -->
              <template v-if="form.it.line_installed === 'Ja'">
                <div>
                  <label class="label">Welche Art / Anschluss? *</label>
                  <select v-model="form.it.line_type" :class="sc('it.line_type')">
                    <option value="">Bitte wählen</option>
                    <option>DSL</option>
                    <option>Glasfaser</option>
                  </select>
                </div>
                <div class="md:col-span-2">
                  <label class="label">Wo befindet sie sich? *</label>
                  <textarea v-model="form.it.line_location" :class="fieldClass('it.line_location')"
                            rows="2" class="resize-none" />
                </div>
              </template>

              <!-- Nein → Vermieter -->
              <template v-if="form.it.line_installed === 'Nein'">
                <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20
                            px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  📌 Vermieter wird mit der Installation beauftragt.
                </div>
                <div>
                  <label class="label">Vermieter – Name *</label>
                  <input v-model="form.it.landlord_name" :class="fieldClass('it.landlord_name')" />
                </div>
                <div>
                  <label class="label">Vermieter – Kontaktdaten *</label>
                  <input v-model="form.it.landlord_contact" :class="fieldClass('it.landlord_contact')" />
                </div>
              </template>

            </div>
          </div>

          <!-- ── Marketing ── -->
          <div class="card space-y-4">
            <h2 class="section-title">Marketing</h2>
            <div>
              <label class="label">Öffnungszeiten der Niederlassung *</label>
              <textarea v-model="form.marketing.opening_hours"
                        :class="fieldClass('marketing.opening_hours')"
                        rows="4" class="resize-none" />
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
.label         { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
</style>