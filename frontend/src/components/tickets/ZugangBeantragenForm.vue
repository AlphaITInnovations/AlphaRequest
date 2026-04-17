<script setup lang="ts">
import UserSelect from '@/components/UserSelect.vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useZugangBeantragen, Phase } from '@/composables/useZugangBeantragen'

const props = defineProps<{
  ctx: ReturnType<typeof useZugangBeantragen>
  phase: Phase
}>()

const {
  form, companies, departments, submitting, fieldClass, isInvalid,
  validationTriggered, generatePersonalnummer, onSignatureTitleInput,
} = props.ctx

const BUNDESLAENDER = [
  'Baden-Württemberg','Bayern','Berlin','Brandenburg','Bremen','Hamburg',
  'Hessen','Mecklenburg-Vorpommern','Niedersachsen','Nordrhein-Westfalen',
  'Rheinland-Pfalz','Saarland','Sachsen','Sachsen-Anhalt','Schleswig-Holstein','Thüringen',
]

const selectClass = (path: string) =>
  fieldClass(path).replace('focus:ring-2', '').replace('placeholder-gray-400 dark:placeholder-gray-500', '')

const checkboxClass = 'h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30 bg-white dark:bg-[#263040]'
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
            :accountable-name="form.accountable?.name"
            :accountable-error="validationTriggered && isInvalid('accountable')"
            @update:priority="form.priority = $event"
            @update:comment="form.comment = $event"
            @update:accountable="form.accountable = $event"
          />
        </div>
      </aside>

      <!-- ── Main: Formularfelder ── -->
      <section class="flex-1 space-y-6">

        <!-- ═══════════════════════════════
             A. BASISDATEN
        ═══════════════════════════════ -->
        <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-6 space-y-8">

          <h2 class="text-lg font-semibold text-[#3EAAB8]">Basisdaten</h2>

          <!-- Stammdaten -->
          <div class="space-y-4">
            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Stammdaten</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

              <div>
                <label class="label">Vorname *</label>
                <input v-model="form.personal.first_name" :class="fieldClass('personal.first_name')" placeholder="Max" />
              </div>
              <div>
                <label class="label">Nachname *</label>
                <input v-model="form.personal.last_name" :class="fieldClass('personal.last_name')" placeholder="Mustermann" />
              </div>
              <div>
                <label class="label">Titel *</label>
                <input v-model="form.personal.title" :class="fieldClass('personal.title')" placeholder="z. B. Niederlassungsleiter" />
              </div>
              <div>
                <label class="label">Eintrittsdatum (laut Vertrag) *</label>
                <input type="date" v-model="form.personal.start_date" :class="fieldClass('personal.start_date')" />
              </div>

              <!-- Privatadresse: Straße, PLZ, Ort -->
              <div class="md:col-span-2">
                <label class="label">Straße (Privatadresse) *</label>
                <input v-model="form.personal.private_street" :class="fieldClass('personal.private_street')" placeholder="Musterstraße 1" />
              </div>
              <div>
                <label class="label">Postleitzahl *</label>
                <input v-model="form.personal.private_zip"
                       @input="form.personal.private_zip = form.personal.private_zip.replace(/\D/g,'').slice(0,5)"
                       :class="fieldClass('personal.private_zip')" inputmode="numeric" maxlength="5" placeholder="12345" />
              </div>
              <div>
                <label class="label">Ort *</label>
                <input v-model="form.personal.private_city" :class="fieldClass('personal.private_city')" placeholder="Musterstadt" />
              </div>

              <div>
                <label class="label">Homeoffice *</label>
                <select v-model="form.personal.homeoffice" :class="selectClass('personal.homeoffice')">
                  <option value="">Bitte wählen</option>
                  <option>Ja</option>
                  <option>Lt. Vertrag</option>
                  <option>Nein</option>
                </select>
              </div>
              <div>
                <label class="label">Arbeitszeit (Std./Woche) *</label>
                <input v-model="form.personal.weekly_hours"
                       @input="form.personal.weekly_hours = (form.personal.weekly_hours).replace(/\D/g, '')"
                       :class="fieldClass('personal.weekly_hours')" inputmode="numeric" placeholder="40" />
              </div>

              <!-- Personalnummer -->
              <div class="md:col-span-2">
                <label class="label">Personalnummer *</label>
                <div v-if="phase === 'create'" class="space-y-2">
                  <button
                    type="button"
                    @click="generatePersonalnummer"
                    :disabled="!!form.personal.personal_number"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded-xl border
                           border-[#3EAAB8]/30 text-[#3EAAB8] bg-[#3EAAB8]/5
                           hover:bg-[#3EAAB8]/10 text-sm font-medium transition
                           disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Personalnummer generieren
                  </button>
                  <div v-if="form.personal.personal_number"
                       class="flex items-center justify-between px-4 py-2 rounded-xl
                              bg-[#3EAAB8]/5 border border-[#3EAAB8]/30">
                    <span class="font-mono text-sm text-[#3EAAB8]">{{ form.personal.personal_number }}</span>
                    <span class="text-xs font-medium text-[#3EAAB8]">generiert</span>
                  </div>
                  <p v-if="validationTriggered && isInvalid('personal.personal_number')"
                     class="text-xs text-red-500">
                    Pflichtfeld – bitte Personalnummer generieren.
                  </p>
                </div>
                <input v-else v-model="form.personal.personal_number"
                       :class="fieldClass('personal.personal_number')"
                       readonly class="opacity-80 cursor-not-allowed" />
              </div>

            </div>
          </div>

          <!-- Organisation -->
          <div class="space-y-4">
            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Organisation</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

              <!-- Abteilung Dropdown -->
              <div>
                <label class="label">Abteilung *</label>
                <select v-model="form.personal.department" :class="selectClass('personal.department')">
                  <option value="">Bitte wählen</option>
                  <option value="Keine">Keine</option>
                  <option v-for="dept in departments" :key="dept.id" :value="dept.name">{{ dept.name }}</option>
                  <option value="Sonstige">Sonstige</option>
                </select>
              </div>
              <!-- Sonstige Freitextfeld -->
              <div v-if="form.personal.department === 'Sonstige'">
                <label class="label">Abteilung angeben *</label>
                <input v-model="form.personal.department_other"
                       :class="fieldClass('personal.department_other')"
                       placeholder="Abteilungsname eingeben" />
              </div>

              <div>
                <label class="label">Kostenstelle *</label>
                <input v-model="form.personal.cost_center"
                       @input="form.personal.cost_center = form.personal.cost_center.replace(/\D/g, '')"
                       :class="fieldClass('personal.cost_center')" inputmode="numeric" />
              </div>
              <div>
                <label class="label">Niederlassung *</label>
                <input v-model="form.personal.location" :class="fieldClass('personal.location')" />
              </div>
              <div>
                <label class="label">Bundesland *</label>
                <select v-model="form.personal.federal_state" :class="selectClass('personal.federal_state')">
                  <option value="">Bitte wählen</option>
                  <option v-for="bl in BUNDESLAENDER" :key="bl">{{ bl }}</option>
                </select>
              </div>
              <div>
                <label class="label">Firma lt. Arbeitsvertrag *</label>
                <select v-model="form.personal.contract_company" :class="selectClass('personal.contract_company')">
                  <option value="">Bitte wählen</option>
                  <option v-for="c in companies" :key="c">{{ c }}</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Beziehungen -->
          <div class="space-y-4">
            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Beziehungen</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div :class="validationTriggered && isInvalid('personal.supervisor_hr_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
                <UserSelect
                  label="Vorgesetzter (vertraglich) *"
                  :model-value="form.personal.supervisor_hr_id ? { id: form.personal.supervisor_hr_id, name: form.personal.supervisor_hr_name } : null"
                  @update:model-value="v => { form.personal.supervisor_hr_id = v?.id ?? ''; form.personal.supervisor_hr_name = v?.name ?? '' }"
                />
              </div>
              <div :class="validationTriggered && isInvalid('personal.contact_person_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
                <UserSelect
                  label="Ansprechpartner für Rückfragen *"
                  :model-value="form.personal.contact_person_id ? { id: form.personal.contact_person_id, name: form.personal.contact_person_name } : null"
                  @update:model-value="v => { form.personal.contact_person_id = v?.id ?? ''; form.personal.contact_person_name = v?.name ?? '' }"
                />
              </div>
            </div>
          </div>

          <!-- Timebutler -->
          <div class="space-y-4">
            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Timebutler</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Urlaubsanspruch pro Jahr *</label>
                <input v-model="form.it.timebutler.vacation_year"
                       @input="form.it.timebutler.vacation_year = form.it.timebutler.vacation_year.replace(/\D/g, '')"
                       :class="fieldClass('it.timebutler.vacation_year')" inputmode="numeric" placeholder="30" />
              </div>
              <div class="md:col-span-2" :class="validationTriggered && isInvalid('it.timebutler.supervisor_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
                <UserSelect
                  label="Wer soll den Urlaub freigeben? *"
                  :model-value="form.it.timebutler.supervisor_id ? { id: form.it.timebutler.supervisor_id, name: form.it.timebutler.supervisor_name } : null"
                  @update:model-value="v => { form.it.timebutler.supervisor_id = v?.id ?? ''; form.it.timebutler.supervisor_name = v?.name ?? '' }"
                />
              </div>
            </div>
          </div>

          <!-- Fuhrpark -->
          <div class="space-y-4">
            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Fuhrpark</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Dienstwagen *</label>
                <select v-model="form.fuhrpark.car" :class="selectClass('fuhrpark.car')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <template v-if="form.fuhrpark.car === 'Ja'">
                <div>
                  <label class="label">Fahrzeuggruppe (1–7) *</label>
                  <select v-model="form.fuhrpark.car_class" :class="selectClass('fuhrpark.car_class')">
                    <option value="">Bitte wählen</option>
                    <option v-for="n in 7" :key="n">{{ n }}</option>
                  </select>
                </div>
                <div>
                  <label class="label">Benötigt ab? *</label>
                  <input type="date" v-model="form.fuhrpark.car_from" :class="fieldClass('fuhrpark.car_from')" />
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- ═══════════════════════════════
             B. IT / SYSTEMDATEN (nur edit)
        ═══════════════════════════════ -->
        <template v-if="phase === 'edit'">

          <!-- IT Systemdaten -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-8">
            <h2 class="text-lg font-semibold text-[#3EAAB8]">IT / Systemdaten</h2>

            <!-- Firma (Signatur / Webseite) – ehemals unter "Allgemein" -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Firma (Signatur / Webseite)</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label class="label">Firma *</label>
                  <select v-model="form.it.appearance_company" :class="selectClass('it.appearance_company')">
                    <option value="">–</option>
                    <option v-for="c in companies" :key="c">{{ c }}</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- E-Mail-Signatur -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">E-Mail-Signatur</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label class="label">Titel (Signatur) *</label>
                  <input v-model="form.it.signature.title"
                         @input="onSignatureTitleInput"
                         :class="fieldClass('it.signature.title')"
                         placeholder="Wird automatisch aus Basisdaten übernommen" />
                  <p class="text-xs text-gray-400 mt-1">Wird aus dem Titel in den Basisdaten vorbefüllt, kann aber angepasst werden.</p>
                </div>
                <div>
                  <label class="label">Straße *</label>
                  <input v-model="form.it.signature.street" :class="fieldClass('it.signature.street')" />
                </div>
                <div>
                  <label class="label">Postleitzahl *</label>
                  <input v-model="form.it.signature.zip"
                         @input="form.it.signature.zip = form.it.signature.zip.replace(/\D/g,'').slice(0,5)"
                         :class="fieldClass('it.signature.zip')" inputmode="numeric" maxlength="5" />
                </div>
                <div>
                  <label class="label">Ort *</label>
                  <input v-model="form.it.signature.city" :class="fieldClass('it.signature.city')" />
                </div>
              </div>
            </div>

            <!-- Software -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Software</h3>
              <div class="space-y-3">
                <div class="flex flex-wrap gap-x-8 gap-y-3">
                  <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    <input type="checkbox" v-model="form.it.software.datev" :class="checkboxClass" />
                    DATEV
                  </label>
                  <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    <input type="checkbox" v-model="form.it.software.persopro" :class="checkboxClass" />
                    PersoPro
                  </label>
                  <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    <input type="checkbox" v-model="form.it.software.timejob" :class="checkboxClass" />
                    TimeJob
                  </label>
                  <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    <input type="checkbox" v-model="form.it.software.zvoove" :class="checkboxClass" />
                    Zvoove
                  </label>
                </div>

                <!-- DATEV Rechte (wenn angehakt) -->
                <div v-if="form.it.software.datev" class="mt-2">
                  <label class="label">DATEV Rechte</label>
                  <textarea v-model="form.it.software.datev_rights"
                            :class="fieldClass('it.software.datev_rights')"
                            rows="3" class="resize-none"
                            placeholder="DATEV Rechte wie Max Mustermann" />
                </div>
              </div>

              <!-- Festnetz-Telefonnummer beantragen -->
              <div class="pt-2">
                <div class="flex items-start gap-4">
                  <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer whitespace-nowrap pt-2.5">
                    <input type="checkbox" v-model="form.it.phone_order.enabled" :class="checkboxClass" />
                    Festnetz-Telefonnummer beantragen
                  </label>
                  <div v-if="form.it.phone_order.enabled" class="flex-1">
                    <label class="label">Aus welcher Niederlassung?</label>
                    <input v-model="form.it.phone_order.location"
                           :class="fieldClass('it.phone_order.location')"
                           placeholder="Niederlassung für Rufnummer" />
                  </div>
                </div>
              </div>

              <!-- Weitere Software -->
              <div class="pt-2">
                <label class="label">Weitere Software</label>
                <textarea v-model="form.it.other_systems"
                          :class="fieldClass('it.other_systems')"
                          rows="3" class="resize-none"
                          placeholder="z. B. weitere benötigte Programme" />
              </div>
            </div>

            <!-- Postfächer & Kostenstellen -->
            <div class="space-y-4">
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Postfächer & Kostenstellen</h3>
              <div class="space-y-4">

                <!-- Infopostfach der Niederlassung (standardmäßig angehakt) -->
                <label class="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                  <input type="checkbox" v-model="form.it.mailboxes.info_mailbox" :class="checkboxClass" />
                  Infopostfach der Niederlassung
                </label>

                <!-- Zusätzliche Postfächer -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label class="label">Zusätzliche Postfächer?</label>
                    <select v-model="form.it.mailboxes.additional" :class="selectClass('it.mailboxes.additional')">
                      <option value="">–</option>
                      <option>Ja</option>
                      <option>Nein</option>
                    </select>
                  </div>
                  <div v-if="form.it.mailboxes.additional === 'Ja'" class="md:col-span-2">
                    <label class="label">Postfächer eintragen *</label>
                    <textarea v-model="form.it.mailboxes.notes"
                              :class="fieldClass('it.mailboxes.notes')"
                              rows="3" class="resize-none"
                              placeholder="z. B. max.mustermann@alphaconsult.org" />
                  </div>
                </div>

                <!-- Zusätzliche Kostenstellen / Niederlassungen -->
                <div>
                  <label class="label">Zusätzliche Kostenstellen / Niederlassungen</label>
                  <p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">
                    z.&nbsp;B. für Drucker oder Rechte aufs Niederlassungslaufwerk
                  </p>
                  <textarea v-model="form.it.additional_cost_centers"
                            :class="fieldClass('it.additional_cost_centers')"
                            rows="3" class="resize-none" />
                </div>
              </div>
            </div>

            <!-- Hardware-Hinweis -->
            <div class="rounded-xl border border-amber-300/50 bg-amber-50 dark:bg-amber-900/10
                        dark:border-amber-500/20 px-4 py-3">
              <div class="flex items-start gap-2.5">
                <svg class="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                  <p class="text-sm font-medium text-amber-800 dark:text-amber-300">Hardware-Bestellungen</p>
                  <p class="text-sm text-amber-700 dark:text-amber-400 mt-0.5">
                    Bitte bestellen Sie IT-Hardware, Mobiltelefone und Festnetzrufnummern weiterhin direkt über IT@alphaconsult.org
                  </p>
                </div>
              </div>
            </div>
          </div>
        </template>

      </section>
    </div>

    <!-- Action Bar -->
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
.label {
  @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5;
}
</style>