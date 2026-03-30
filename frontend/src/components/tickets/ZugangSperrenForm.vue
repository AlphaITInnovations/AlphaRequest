<script setup lang="ts">
import UserSelect from '@/components/UserSelect.vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useZugangSperren, Phase } from '@/composables/useZugangSperren'

const props = defineProps<{
  ctx: ReturnType<typeof useZugangSperren>
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

        <!-- ── Basisdaten (Phase 1 + 2) ── -->
        <div class="card space-y-4">
          <h2 class="section-title">Basisdaten</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Vorname *</label>
              <input v-model="form.personal.first_name" :class="fieldClass('personal.first_name')" />
            </div>
            <div>
              <label class="label">Nachname *</label>
              <input v-model="form.personal.last_name" :class="fieldClass('personal.last_name')" />
            </div>
            <div>
              <label class="label">Kostenstelle *</label>
              <input v-model="form.personal.cost_center"
                     @input="form.personal.cost_center = form.personal.cost_center.replace(/\D/g, '')"
                     :class="fieldClass('personal.cost_center')" inputmode="numeric" />
            </div>
            <div>
              <label class="label">Firma lt. Arbeitsvertrag *</label>
              <select v-model="form.personal.contract_company" :class="sc('personal.contract_company')">
                <option value="">Bitte wählen</option>
                <option v-for="c in companies" :key="c">{{ c }}</option>
              </select>
            </div>
            <div>
              <label class="label">Austrittsdatum *</label>
              <input type="date" v-model="form.personal.exit_date"
                     :class="fieldClass('personal.exit_date')" />
            </div>
            <div>
              <label class="label">Abfindungsvereinbarung *</label>
              <select v-model="form.personal.severance_agreement" :class="sc('personal.severance_agreement')">
                <option value="">Bitte wählen</option>
                <option>Ja</option>
                <option>Nein</option>
              </select>
            </div>
          </div>
        </div>

        <!-- ── IT (nur edit) ── -->
        <template v-if="phase === 'edit'">
          <div class="card space-y-6">
            <h2 class="section-title">IT</h2>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

              <!-- Mailweiterleitung -->
              <div>
                <label class="label">Mailweiterleitung? *</label>
                <select v-model="form.it.mail_forwarding" :class="sc('it.mail_forwarding')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
                <p class="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  ⏱ <strong>Maximal 30 Tage.</strong> Nur an <strong>eine</strong> Person.
                </p>
              </div>
              <div v-if="form.it.mail_forwarding === 'Ja'">
                <label class="label">Weiterleiten an *</label>
                <input v-model="form.it.mail_forward_to" :class="fieldClass('it.mail_forward_to')"
                       placeholder="z. B. vorname.nachname@firma.de" />
              </div>

              <!-- Postfachzugriff -->
              <div>
                <label class="label">Postfachzugriff gewähren? *</label>
                <select v-model="form.it.mailbox_access" :class="sc('it.mailbox_access')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
                <p class="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  ⏱ <strong>Maximal 30 Tage.</strong> Mehrere Personen möglich.
                </p>
              </div>
              <div v-if="form.it.mailbox_access === 'Ja'" class="md:col-span-2">
                <label class="label">Zugriff für (mehrere Personen möglich) *</label>
                <textarea v-model="form.it.mailbox_access_for"
                          :class="fieldClass('it.mailbox_access_for')"
                          rows="3" class="resize-none"
                          placeholder="Eine Person pro Zeile oder komma-getrennt" />
              </div>

            </div>

            <!-- Hinweis -->
            <div class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20
                        px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              📌 <strong>Wichtiger Hinweis:</strong> Postfächer werden weiterhin gesichert.
              <strong>Neue E-Mails werden jedoch nicht mehr zugestellt.</strong>
            </div>

            <!-- Abwesenheitsnotiz -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Abwesenheitsnotiz aktivieren? *</label>
                <select v-model="form.it.auto_reply" :class="sc('it.auto_reply')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div v-if="form.it.auto_reply === 'Ja'" class="md:col-span-2">
                <label class="label">Text der Abwesenheitsnotiz *</label>
                <textarea v-model="form.it.auto_reply_text"
                          :class="fieldClass('it.auto_reply_text')"
                          rows="6" class="resize-none font-mono text-xs" />
                <p class="mt-1 text-xs text-gray-500">
                  Platzhalter prüfen: <code>&lt;Name&gt;</code>, <code>&lt;Ersatzmailadresse&gt;</code>
                </p>
              </div>
            </div>
          </div>

          <!-- ── Fuhrpark ── -->
          <div class="card space-y-4">
            <h2 class="section-title">Fuhrpark</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="label">Dienstwagen vorhanden? *</label>
                <select v-model="form.fuhrpark.car" :class="sc('fuhrpark.car')">
                  <option value="">–</option>
                  <option>Ja</option>
                  <option>Nein</option>
                </select>
              </div>
              <div v-if="form.fuhrpark.car === 'Ja'">
                <label class="label">Rückgabedatum *</label>
                <input type="date" v-model="form.fuhrpark.car_return_date"
                       :class="fieldClass('fuhrpark.car_return_date')" />
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