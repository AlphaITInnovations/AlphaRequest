<script setup lang="ts">
import { ref } from 'vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import UserSelect from '@/components/UserSelect.vue'
import { VORQUALIFIZIERUNG_OPTIONEN } from '@/composables/useMarketingStelle'
import type { useMarketingStelle, Phase } from '@/composables/useMarketingStelle'

const props = defineProps<{
  ctx: ReturnType<typeof useMarketingStelle>
  phase: Phase
}>()

const { form, companies, submitting, fieldClass, isInvalid, validationTriggered } = props.ctx

const BESCHAEFTIGUNGSARTEN = ['Vollzeit', 'Teilzeit', 'Minijob', 'Befristet', 'Praktikum', 'Werkstudent']

const newCustomFrage = ref('')
function addCustomFrage() {
  const v = newCustomFrage.value.trim()
  if (v && !form.stelle.vorqualifizierung_custom.includes(v)) {
    form.stelle.vorqualifizierung_custom.push(v)
  }
  newCustomFrage.value = ''
}
function removeCustomFrage(i: number) {
  form.stelle.vorqualifizierung_custom.splice(i, 1)
}

const selectClass = (path: string) =>
  fieldClass(path).replace('placeholder-gray-400 dark:placeholder-gray-500', '')

const radioClass = (selected: boolean) =>
  `flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition ${
    selected
      ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
      : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'
  }`

const checkboxClass = (selected: boolean) =>
  `w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center text-xs ${
    selected ? 'bg-[#3EAAB8] border-[#3EAAB8] text-white' : 'border-gray-300 dark:border-white/20'
  }`
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

        <!-- ── Freigabe ────────────────────────────────────────────── -->
        <div class="card">
          <h2 class="text-xl font-bold text-gray-900 dark:text-white mb-1">✅ Freigabe erteilt durch</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="label">Name</label>
              <input :value="form.stelle.freigabe_name" readonly class="input-ro" />
            </div>
            <div>
              <label class="label">E-Mail</label>
              <input :value="form.stelle.freigabe_email" readonly class="input-ro" />
            </div>
          </div>
        </div>

        <!-- ── Niederlassung & Gesellschaft ────────────────────────── -->
        <div class="card space-y-4">
          <h2 class="section-title">🏢 Niederlassung & Gesellschaft</h2>
          <div class="grid grid-cols-1 gap-4">
            <div>
              <label class="label">Welche Niederlassung?{{ phase === 'edit' ? ' *' : '' }}</label>
              <input v-model="form.stelle.niederlassung"
                     :class="fieldClass('stelle.niederlassung')"
                     placeholder="z. B. ACP Neumünster" />
            </div>
            <div>
              <label class="label">Für welche Gesellschaft ist die Anzeige vorgesehen?{{ phase === 'edit' ? ' *' : '' }}</label>
              <select v-model="form.stelle.gesellschaft" :class="selectClass('stelle.gesellschaft')">
                <option value="">Bitte wählen</option>
                <option v-for="c in companies" :key="c">{{ c }}</option>
              </select>
            </div>
          </div>
        </div>

        <!-- ── Stelle ───────────────────────────────────────────────── -->
        <div class="card space-y-4">
          <h2 class="section-title">💼 Zur beworbenen Stelle</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="md:col-span-2">
              <label class="label">Gesuchte Berufsbezeichnung{{ phase === 'edit' ? ' *' : '' }}</label>
              <input v-model="form.stelle.berufsbezeichnung"
                     :class="fieldClass('stelle.berufsbezeichnung')"
                     placeholder="z. B. Projektmanager:in Marketing (m/w/d)" />
            </div>
            <div>
              <label class="label">Beschäftigungsart{{ phase === 'edit' ? ' *' : '' }}</label>
              <select v-model="form.stelle.beschaeftigungsart" :class="selectClass('stelle.beschaeftigungsart')">
                <option value="">Bitte wählen</option>
                <option v-for="art in BESCHAEFTIGUNGSARTEN" :key="art">{{ art }}</option>
              </select>
            </div>
            <div>
              <label class="label">Kostenstelle{{ phase === 'edit' ? ' *' : '' }}</label>
              <input v-model="form.stelle.kostenstelle"
                     :class="fieldClass('stelle.kostenstelle')"
                     placeholder="z. B. 4711" />
            </div>
            <div class="md:col-span-2">
              <UserSelect
                :label="`Wer bearbeitet die Talention-Kampagne / Wer ist verantwortlich?${phase === 'edit' ? ' *' : ''}`"
                placeholder="Mitarbeiter:in auswählen…"
                :model-value="form.stelle.talention_verantwortlicher_id
                  ? { id: form.stelle.talention_verantwortlicher_id, name: form.stelle.talention_verantwortlicher_name }
                  : null"
                @update:model-value="v => {
                  form.stelle.talention_verantwortlicher_id   = v?.id ?? ''
                  form.stelle.talention_verantwortlicher_name = v?.name ?? ''
                }"
              />
              <p v-if="validationTriggered && isInvalid('stelle.talention_verantwortlicher_id')"
                 class="text-xs text-red-500 mt-1">Pflichtfeld</p>
            </div>
          </div>
        </div>

        <!-- ── Stellendetails ───────────────────────────────────────── -->
        <div class="card space-y-4">
          <h2 class="section-title">⭐ Stellendetails & Benefits</h2>
          <div class="space-y-4">
            <div>
              <label class="label">Mindestens 3 Benefits{{ phase === 'edit' ? ' *' : '' }}</label>
              <p class="text-xs text-gray-400 mb-1.5">Kommagetrennt, z. B. Weihnachtsgeld, 30 Tage Urlaub, unbefristeter Vertrag</p>
              <textarea v-model="form.stelle.benefits" :class="fieldClass('stelle.benefits')"
                        rows="3" class="resize-none" />
            </div>
            <div>
              <label class="label">Ist eine Gehaltsangabe in der Anzeige gewünscht?{{ phase === 'edit' ? ' *' : '' }}</label>
              <div class="grid grid-cols-2 gap-3 mt-1">
                <label v-for="opt in ['Ja', 'Nein']" :key="opt" :class="radioClass(form.stelle.gehaltsangabe === opt)">
                  <input type="radio" class="hidden" :value="opt" v-model="form.stelle.gehaltsangabe" />
                  <span class="text-sm font-medium">{{ opt }}</span>
                </label>
              </div>
            </div>
            <div v-if="form.stelle.gehaltsangabe === 'Ja'">
              <label class="label">Beworbenes Gehalt *</label>
              <input v-model="form.stelle.gehalt" :class="fieldClass('stelle.gehalt')"
                     placeholder="z. B. 2.800 – 3.200 € oder ab 2.800 €" />
            </div>
            <div>
              <label class="label">Notwendige Bedingungen für Bewerber{{ phase === 'edit' ? ' *' : '' }}</label>
              <p class="text-xs text-gray-400 mb-1.5">Nur zwingend nötige Voraussetzungen (z. B. Führerschein, Schichtbereitschaft)</p>
              <textarea v-model="form.stelle.bedingungen_notwendig"
                        :class="fieldClass('stelle.bedingungen_notwendig')"
                        rows="3" class="resize-none" />
            </div>
            <div>
              <label class="label">Wünschenswerte Qualifikationen (optional)</label>
              <textarea v-model="form.stelle.qualifikationen_nice"
                        class="w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                               bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                               focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition resize-none"
                        rows="3" />
            </div>
          </div>
        </div>

        <!-- ── Erstellung der Anzeige ───────────────────────────────── -->
        <div class="card space-y-4">
          <h2 class="section-title">📅 Erstellung der Anzeige</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Wann soll die Anzeige online gehen?{{ phase === 'edit' ? ' *' : '' }}</label>
              <input type="date" v-model="form.stelle.online_datum" :class="fieldClass('stelle.online_datum')" />
            </div>
            <div>
              <label class="label">Soll die Anzeige open end laufen?{{ phase === 'edit' ? ' *' : '' }}</label>
              <div class="grid grid-cols-2 gap-3 mt-1">
                <label v-for="opt in ['Ja', 'Nein']" :key="opt" :class="radioClass(form.stelle.open_end === opt)">
                  <input type="radio" class="hidden" :value="opt" v-model="form.stelle.open_end" />
                  <span class="text-sm font-medium">{{ opt }}</span>
                </label>
              </div>
            </div>
            <div v-if="form.stelle.open_end === 'Nein'">
              <label class="label">Enddatum * <span class="text-xs font-normal text-gray-400">(mind. 3 Monate)</span></label>
              <input type="date" v-model="form.stelle.end_datum" :class="fieldClass('stelle.end_datum')" />
            </div>
            <div>
              <label class="label">In welchen Städten ausspielen?{{ phase === 'edit' ? ' *' : '' }}</label>
              <input v-model="form.stelle.staedte" :class="fieldClass('stelle.staedte')"
                     placeholder="z. B. München, Augsburg, Ingolstadt" />
            </div>
            <div>
              <label class="label">Radius pro Stadt (km)?{{ phase === 'edit' ? ' *' : '' }} <span class="text-xs font-normal text-gray-400">mind. 20 km</span></label>
              <input v-model="form.stelle.radius" :class="fieldClass('stelle.radius')" placeholder="z. B. 25–30 km" />
            </div>
            <div>
              <label class="label">Max. Budget pro Monat (€)?{{ phase === 'edit' ? ' *' : '' }}</label>
              <p class="text-xs text-gray-400 mb-1.5">Empfehlung: mind. 500 € / Anzeige / Monat / Niederlassung</p>
              <input v-model="form.stelle.budget" :class="fieldClass('stelle.budget')"
                     placeholder="z. B. 500" inputmode="numeric" />
            </div>
          </div>
        </div>

        <!-- ── Funnel ───────────────────────────────────────────────── -->
        <div class="card space-y-4">
          <h2 class="section-title">🎯 Erstellung des Funnels</h2>
          <div class="space-y-5">

            <div>
              <label class="label">Fragen zur Vorqualifizierung im Funnel</label>
              <p class="text-xs text-gray-400 mb-2">Mehrfachauswahl möglich</p>
              <div class="space-y-2">
                <label v-for="opt in VORQUALIFIZIERUNG_OPTIONEN" :key="opt"
                       class="flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer transition text-sm"
                       :class="form.stelle.vorqualifizierung_fragen.includes(opt)
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="checkbox" class="hidden" :value="opt" v-model="form.stelle.vorqualifizierung_fragen" />
                  <span :class="checkboxClass(form.stelle.vorqualifizierung_fragen.includes(opt))" class="mt-0.5">
                    <span v-if="form.stelle.vorqualifizierung_fragen.includes(opt)">✓</span>
                  </span>
                  <span>{{ opt }}</span>
                </label>
              </div>
            </div>

            <div>
              <label class="label">Eigene Vorqualifizierungsfragen (optional)</label>
              <div v-if="form.stelle.vorqualifizierung_custom.length" class="flex flex-wrap gap-2 mb-2">
                <span v-for="(f, i) in form.stelle.vorqualifizierung_custom" :key="i"
                      class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm
                             bg-[#3EAAB8]/10 text-[#3EAAB8] border border-[#3EAAB8]/20">
                  {{ f }}
                  <button type="button" @click="removeCustomFrage(i)"
                          class="hover:text-red-500 transition text-base leading-none">&times;</button>
                </span>
              </div>
              <div class="flex gap-2">
                <input v-model="newCustomFrage"
                       @keydown.enter.prevent="addCustomFrage"
                       class="flex-1 rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                              bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                              focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition"
                       placeholder="Eigene Frage eingeben und Enter drücken …" />
                <button type="button" @click="addCustomFrage"
                        class="px-4 py-2.5 rounded-xl bg-[#3EAAB8] text-white text-sm font-medium
                               hover:bg-[#35909c] transition flex-shrink-0">
                  + Hinzufügen
                </button>
              </div>
            </div>

            <div>
              <label class="label">Häufige Bewerberfragen & Antworten (FAQ){{ phase === 'edit' ? ' *' : '' }}</label>
              <p class="text-xs text-gray-400 mb-1.5">Format: „Frage: … / Antwort: …", eine Zeile pro FAQ</p>
              <textarea v-model="form.stelle.faq" :class="fieldClass('stelle.faq')"
                        rows="4" class="resize-none"
                        placeholder="z. B. Gehalt (20–20,30 € i.d.R.), Schicht (2-Schicht), Sprache (Deutsch)" />
            </div>

          </div>
        </div>

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
.label         { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
.card          { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6; }
.section-title { @apply text-lg font-semibold text-[#3EAAB8] mb-2; }
.input-ro      { @apply w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                        bg-gray-50 dark:bg-[#1a2333] text-gray-500 dark:text-gray-400 cursor-default; }
</style>