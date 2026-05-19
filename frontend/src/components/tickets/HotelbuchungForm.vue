<script setup lang="ts">
import TicketActionBar from '@/components/TicketActionBar.vue'
import UserSelect from '@/components/UserSelect.vue'
import type { useHotelbuchung } from '@/composables/useHotelbuchung'

defineProps<{
  ctx: ReturnType<typeof useHotelbuchung>
}>()
</script>

<template>
  <div class="max-w-4xl mx-auto">

    <!-- Error Bar -->
    <div v-if="ctx.validationTriggered.value && ctx.errors.value?.length"
         class="mb-6 rounded-xl border border-red-300 bg-red-50 dark:bg-red-900/20
                dark:border-red-500/30 px-4 py-3 text-red-800 dark:text-red-300">
      <p class="font-semibold">Bitte alle Pflichtfelder ausfüllen.</p>
      <p class="text-sm mt-0.5">{{ ctx.errors.value.length }} Fehler gefunden.</p>
    </div>

    <section class="space-y-6">

      <!-- ═══ Antragsteller ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">👤 Angaben zur antragstellenden Person</h2>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="label">Name, Vorname *</label>
            <input v-model="ctx.form.buchung.antragsteller_name" :class="ctx.fieldClass('buchung.antragsteller_name')" readonly class="opacity-70 cursor-not-allowed" />
          </div>
          <div>
            <label class="label">E-Mail *</label>
            <input v-model="ctx.form.buchung.antragsteller_email" :class="ctx.fieldClass('buchung.antragsteller_email')" readonly class="opacity-70 cursor-not-allowed" />
          </div>
          <div>
            <label class="label">Niederlassung *</label>
            <input v-model="ctx.form.buchung.niederlassung" :class="ctx.fieldClass('buchung.niederlassung')" placeholder="z. B. Hamburg" />
          </div>
          <div>
            <label class="label">Telefonnummer *</label>
            <input v-model="ctx.form.buchung.telefonnummer" :class="ctx.fieldClass('buchung.telefonnummer')" placeholder="+49 …" />
          </div>
          <div>
            <label class="label">Kostenstelle (zwingend) *</label>
            <input v-model="ctx.form.buchung.kostenstelle"
                   @input="ctx.form.buchung.kostenstelle = ctx.form.buchung.kostenstelle.replace(/\D/g, '')"
                   :class="ctx.fieldClass('buchung.kostenstelle')" inputmode="numeric" placeholder="z. B. 1234" />
          </div>
        </div>
      </div>

      <!-- ═══ Reisedaten ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">📅 Reisedaten</h2>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label class="label">Anreisedatum *</label>
            <input type="date" v-model="ctx.form.buchung.anreisedatum" :class="ctx.fieldClass('buchung.anreisedatum')" />
          </div>
          <div>
            <label class="label">Abreisedatum *</label>
            <input type="date" v-model="ctx.form.buchung.abreisedatum" :class="ctx.fieldClass('buchung.abreisedatum')" />
          </div>
          <div>
            <label class="label">Anzahl Übernachtungen</label>
            <input v-model="ctx.form.buchung.anzahl_naechte"
                   @input="ctx.onNaechteInput(); ctx.form.buchung.anzahl_naechte = ctx.form.buchung.anzahl_naechte.replace(/\D/g, '')"
                   :class="ctx.fieldClass('buchung.anzahl_naechte')" inputmode="numeric"  />
          </div>
        </div>
      </div>

      <!-- ═══ Reiseziel ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">📍 Reiseziel</h2>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="label">Ort / Stadt *</label>
            <input v-model="ctx.form.buchung.ort_stadt" :class="ctx.fieldClass('buchung.ort_stadt')" placeholder="z. B. München" />
          </div>
          <div>
            <label class="label">Partner-Hotel (z. B. MOTEL ONE)</label>
            <input v-model="ctx.form.buchung.partner_hotel" :class="ctx.fieldClass('buchung.partner_hotel')" placeholder="Optional" />
          </div>
          <div class="md:col-span-2">
            <label class="label">Hotelwunsch (optional)</label>
            <input v-model="ctx.form.buchung.hotelwunsch" :class="ctx.fieldClass('buchung.hotelwunsch')" placeholder="Falls ein bestimmtes Hotel gewünscht ist" />
          </div>
        </div>
      </div>

      <!-- ═══ Reiseanlass ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">🎯 Reiseanlass (zwingend auszufüllen) *</h2>

        <!-- Radio-Auswahl -->
        <div class="space-y-3">
          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                 :class="ctx.form.buchung.reiseanlass === 'kundentermin'
                   ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                   : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
            <input type="radio" v-model="ctx.form.buchung.reiseanlass" value="kundentermin" class="hidden" />
            <span class="w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                  :class="ctx.form.buchung.reiseanlass === 'kundentermin' ? 'border-[#3EAAB8]' : 'border-gray-300 dark:border-white/20'">
              <span v-if="ctx.form.buchung.reiseanlass === 'kundentermin'" class="w-2 h-2 rounded-full bg-[#3EAAB8]" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-white">Kundentermin</span>
          </label>

          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                 :class="ctx.form.buchung.reiseanlass === 'besuch_niederlassung'
                   ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                   : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
            <input type="radio" v-model="ctx.form.buchung.reiseanlass" value="besuch_niederlassung" class="hidden" />
            <span class="w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                  :class="ctx.form.buchung.reiseanlass === 'besuch_niederlassung' ? 'border-[#3EAAB8]' : 'border-gray-300 dark:border-white/20'">
              <span v-if="ctx.form.buchung.reiseanlass === 'besuch_niederlassung'" class="w-2 h-2 rounded-full bg-[#3EAAB8]" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-white">Besuch Niederlassung</span>
          </label>

          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                 :class="ctx.form.buchung.reiseanlass === 'sonstiges'
                   ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                   : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
            <input type="radio" v-model="ctx.form.buchung.reiseanlass" value="sonstiges" class="hidden" />
            <span class="w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                  :class="ctx.form.buchung.reiseanlass === 'sonstiges' ? 'border-[#3EAAB8]' : 'border-gray-300 dark:border-white/20'">
              <span v-if="ctx.form.buchung.reiseanlass === 'sonstiges'" class="w-2 h-2 rounded-full bg-[#3EAAB8]" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-white">Sonstiges (Freigabe notwendig)</span>
          </label>
        </div>

        <p v-if="ctx.validationTriggered.value && ctx.isInvalid('buchung.reiseanlass')"
           class="text-xs text-red-500">Bitte einen Reiseanlass auswählen.</p>

        <!-- ── Kundentermin Details ── -->
        <div v-if="ctx.form.buchung.reiseanlass === 'kundentermin'"
             class="p-4 rounded-xl bg-gray-50 dark:bg-[#1A2130] border border-gray-200/80 dark:border-white/[0.06] space-y-4">
          <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Angaben zum Kundentermin</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Kundenname *</label>
              <input v-model="ctx.form.buchung.kunde_name" :class="ctx.fieldClass('buchung.kunde_name')" placeholder="Firmenname / Ansprechpartner" />
            </div>
            <div>
              <label class="label">Anschrift *</label>
              <input v-model="ctx.form.buchung.kunde_anschrift" :class="ctx.fieldClass('buchung.kunde_anschrift')" placeholder="Straße, PLZ, Ort" />
            </div>
            <div class="md:col-span-2">
              <label class="label">Grund des Besuchs *</label>
              <textarea v-model="ctx.form.buchung.kunde_grund" :class="ctx.fieldClass('buchung.kunde_grund')"
                        rows="3" class="resize-none" placeholder="Beschreibung des Termins…" />
            </div>
          </div>
        </div>

        <!-- ── Besuch Niederlassung Details ── -->
        <div v-if="ctx.form.buchung.reiseanlass === 'besuch_niederlassung'"
             class="p-4 rounded-xl bg-gray-50 dark:bg-[#1A2130] border border-gray-200/80 dark:border-white/[0.06] space-y-4">
          <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Angaben zum Niederlassungsbesuch</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Niederlassung (NL) *</label>
              <input v-model="ctx.form.buchung.besuch_niederlassung" :class="ctx.fieldClass('buchung.besuch_niederlassung')" placeholder="z. B. München" />
            </div>
            <div class="md:col-span-2">
              <label class="label">Begründung</label>
              <textarea v-model="ctx.form.buchung.besuch_begruendung" :class="ctx.fieldClass('buchung.besuch_begruendung')"
                        rows="3" class="resize-none" placeholder="Optional" />
            </div>
          </div>
        </div>

        <!-- ── Sonstiges Details ── -->
        <div v-if="ctx.form.buchung.reiseanlass === 'sonstiges'"
             class="p-4 rounded-xl bg-gray-50 dark:bg-[#1A2130] border border-gray-200/80 dark:border-white/[0.06] space-y-4">
          <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">Sonstiger Reiseanlass</h3>
          <div class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200 mb-2">
            Bei sonstigen Reiseanlässen ist eine Genehmigung zwingend erforderlich.
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2">
              <label class="label">Begründung *</label>
              <textarea v-model="ctx.form.buchung.sonstiges_grund" :class="ctx.fieldClass('buchung.sonstiges_grund')"
                        rows="3" class="resize-none" placeholder="Grund der Dienstreise…" />
            </div>
            <div :class="ctx.validationTriggered.value && ctx.isInvalid('buchung.genehmigung_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
              <UserSelect
                label="Genehmigung durch *"
                placeholder="Person auswählen…"
                :model-value="ctx.form.buchung.genehmigung_id
                  ? { id: ctx.form.buchung.genehmigung_id, name: ctx.form.buchung.genehmigung_name }
                  : null"
                @update:model-value="v => {
                  ctx.form.buchung.genehmigung_id   = v?.id ?? ''
                  ctx.form.buchung.genehmigung_name = v?.name ?? ''
                }"
              />
              <p v-if="ctx.validationTriggered.value && ctx.isInvalid('buchung.genehmigung_id')"
                 class="text-xs text-red-500 mt-1">Pflichtfeld</p>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══ Budgetvorgaben ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">💰 Budgetvorgaben gemäß Reisekostenrichtlinie *</h2>

        <div class="space-y-3">
          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                 :class="ctx.form.buchung.budget_bestaetigung === 'unter_120'
                   ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                   : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
            <input type="radio" v-model="ctx.form.buchung.budget_bestaetigung" value="unter_120" class="hidden" />
            <span class="w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                  :class="ctx.form.buchung.budget_bestaetigung === 'unter_120' ? 'border-[#3EAAB8]' : 'border-gray-300 dark:border-white/20'">
              <span v-if="ctx.form.buchung.budget_bestaetigung === 'unter_120'" class="w-2 h-2 rounded-full bg-[#3EAAB8]" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-white">Ich bestätige, dass die Kosten ≤ 120 € pro Nacht inkl. Frühstück liegen</span>
          </label>

          <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                 :class="ctx.form.buchung.budget_bestaetigung === 'abweichung'
                   ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                   : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
            <input type="radio" v-model="ctx.form.buchung.budget_bestaetigung" value="abweichung" class="hidden" />
            <span class="w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                  :class="ctx.form.buchung.budget_bestaetigung === 'abweichung' ? 'border-[#3EAAB8]' : 'border-gray-300 dark:border-white/20'">
              <span v-if="ctx.form.buchung.budget_bestaetigung === 'abweichung'" class="w-2 h-2 rounded-full bg-[#3EAAB8]" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-white">Abweichung erforderlich (Begründung &amp; Freigabe notwendig)</span>
          </label>
        </div>

        <p v-if="ctx.validationTriggered.value && ctx.isInvalid('buchung.budget_bestaetigung')"
           class="text-xs text-red-500">Bitte eine Budgetvorgabe auswählen.</p>

        <!-- Abweichung Details -->
        <div v-if="ctx.form.buchung.budget_bestaetigung === 'abweichung'"
             class="p-4 rounded-xl bg-gray-50 dark:bg-[#1A2130] border border-gray-200/80 dark:border-white/[0.06] space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2">
              <label class="label">Begründung *</label>
              <textarea v-model="ctx.form.buchung.budget_begruendung" :class="ctx.fieldClass('buchung.budget_begruendung')"
                        rows="3" class="resize-none" placeholder="Warum wird das Budget überschritten?" />
            </div>
            <div :class="ctx.validationTriggered.value && ctx.isInvalid('buchung.budget_genehmigung_id') ? 'ring-1 ring-red-400 rounded-xl' : ''">
              <UserSelect
                label="Genehmigung durch *"
                placeholder="Person auswählen…"
                :model-value="ctx.form.buchung.budget_genehmigung_id
                  ? { id: ctx.form.buchung.budget_genehmigung_id, name: ctx.form.buchung.budget_genehmigung_name }
                  : null"
                @update:model-value="v => {
                  ctx.form.buchung.budget_genehmigung_id   = v?.id ?? ''
                  ctx.form.buchung.budget_genehmigung_name = v?.name ?? ''
                }"
              />
              <p v-if="ctx.validationTriggered.value && ctx.isInvalid('buchung.budget_genehmigung_id')"
                 class="text-xs text-red-500 mt-1">Pflichtfeld</p>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══ Besondere Anforderungen ═══ -->
      <div class="card space-y-4">
        <h2 class="text-lg font-semibold text-[#3EAAB8]">📝 Besondere Anforderungen</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 -mt-2">
          z. B. Nähe zum Einsatzort, Parkplatz, spätes Check-in etc.
        </p>
        <textarea v-model="ctx.form.buchung.besondere_anforderungen"
                  :class="ctx.fieldClass('buchung.besondere_anforderungen')"
                  rows="4" class="resize-none"
                  placeholder="Optional – besondere Wünsche hier eintragen" />
      </div>

      <!-- ═══ Hinweis ═══ -->
      <div class="rounded-xl border border-amber-300/50 bg-amber-50 dark:bg-amber-900/10
                  dark:border-amber-500/20 px-4 py-3">
        <div class="flex items-start gap-2.5">
          <svg class="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p class="text-sm text-amber-700 dark:text-amber-400">
            Ich bestätige die Richtigkeit und Vollständigkeit der Angaben. Mir ist bekannt, dass unvollständige Angaben
            (z. B. nur „Kundentermin" ohne Details) dazu führen können, dass keine Buchung bzw. keine spätere Spesenabrechnung erfolgt.
          </p>
        </div>
      </div>

    </section>

    <!-- Action Bar -->
    <TicketActionBar
      :phase="ctx.phase"
      :loading="ctx.submitting.value"
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
.card {
  @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6;
}
</style>