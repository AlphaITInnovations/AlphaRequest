<script setup lang="ts">
import { watch } from 'vue'
import TicketDetails from '@/components/TicketDetails.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import type { useHardware, Phase } from '@/composables/useHardware'

const props = defineProps<{
  ctx: ReturnType<typeof useHardware>
  phase: Phase
}>()

const { form, companies, submitting, fieldClass, isInvalid,
        validationTriggered, hardwareInvalid, resetHardware } = props.ctx

// Hardwareauswahl resetten wenn Mitarbeitertyp wechselt
watch(() => form.hardware.mitarbeiterTyp, resetHardware)

const ARTIKEL = [
  { key: 'Notebook',        icon: '💻', label: 'Notebook' },
  { key: 'MiniPC',          icon: '🖥️', label: 'Mini-PC' },
  { key: 'Dockingstation',  icon: '🔌', label: 'Dockingstation' },
  { key: 'MausUndTastatur', icon: '🖱️', label: 'Maus & Tastatur' },
  { key: 'Headset',         icon: '🎧', label: 'Headset' },
  { key: 'Webcam',          icon: '📷', label: 'Webcam' },
  { key: 'Handy',           icon: '📱', label: 'Handy' },
  { key: 'SIM',             icon: '📶', label: 'SIM-Karte' },
] as const

const selectClass = (path: string) =>
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

        <!-- Mitarbeitertyp -->
        <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-6 space-y-4">
          <h2 class="text-lg font-semibold text-[#3EAAB8]">👤 Mitarbeitertyp</h2>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4"
               :class="validationTriggered && isInvalid('hardware.mitarbeiterTyp') ? 'ring-1 ring-red-400 rounded-xl p-1' : ''">
            <label v-for="typ in ['Bestandsmitarbeiter', 'Neuer Mitarbeiter']" :key="typ"
                   class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                   :class="form.hardware.mitarbeiterTyp === typ
                     ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                     : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
              <input type="radio" class="hidden" :value="typ" v-model="form.hardware.mitarbeiterTyp" />
              <span class="text-sm font-medium text-gray-900 dark:text-white">{{ typ }}</span>
            </label>
          </div>
        </div>

        <!-- Basisdaten -->
        <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-6 space-y-4">
          <h2 class="text-lg font-semibold text-[#3EAAB8]">📇 Basisdaten</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="label">Vorname *</label>
              <input v-model="form.hardware.vorname" :class="fieldClass('hardware.vorname')" placeholder="Max" />
            </div>
            <div>
              <label class="label">Nachname *</label>
              <input v-model="form.hardware.nachname" :class="fieldClass('hardware.nachname')" placeholder="Mustermann" />
            </div>
            <div>
              <label class="label">Kostenstelle *</label>
              <input v-model="form.hardware.kostenstelle"
                     @input="form.hardware.kostenstelle = form.hardware.kostenstelle.replace(/\D/g, '')"
                     :class="fieldClass('hardware.kostenstelle')" inputmode="numeric" />
            </div>
            <div>
              <label class="label">Firma *</label>
              <select v-model="form.hardware.firma" :class="selectClass('hardware.firma')">
                <option value="">Bitte wählen</option>
                <option v-for="c in companies" :key="c">{{ c }}</option>
              </select>
            </div>

            <!-- Adresse -->
            <div class="md:col-span-2 grid grid-cols-6 gap-4">
              <div class="col-span-4">
                <label class="label">Straße *</label>
                <input v-model="form.hardware.addr_strasse" :class="fieldClass('hardware.addr_strasse')" />
              </div>
              <div class="col-span-2">
                <label class="label">Nr. *</label>
                <input v-model="form.hardware.addr_nr" :class="fieldClass('hardware.addr_nr')" />
              </div>
              <div class="col-span-2">
                <label class="label">PLZ *</label>
                <input v-model="form.hardware.addr_plz"
                       @input="form.hardware.addr_plz = form.hardware.addr_plz.replace(/\D/g,'').slice(0,5)"
                       :class="fieldClass('hardware.addr_plz')" inputmode="numeric" maxlength="5" />
              </div>
              <div class="col-span-4">
                <label class="label">Stadt *</label>
                <input v-model="form.hardware.addr_stadt" :class="fieldClass('hardware.addr_stadt')" />
              </div>
              <div class="col-span-6">
                <label class="label">Name am Türschild (optional)</label>
                <input v-model="form.hardware.addr_tuerschild"
                       class="w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                              bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                              focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition" />
              </div>
            </div>

            <div>
              <label class="label">Lieferung bis *</label>
              <input type="date" v-model="form.hardware.lieferungBis" :class="fieldClass('hardware.lieferungBis')" />
            </div>
          </div>
        </div>

        <!-- Hardware – Bestandsmitarbeiter -->
        <template v-if="form.hardware.mitarbeiterTyp === 'Bestandsmitarbeiter'">
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-6">
            <h2 class="text-lg font-semibold text-[#3EAAB8]">🧰 Hardware & Grund</h2>

            <!-- Artikel -->
            <div>
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Hardware auswählen *</h3>
              <div class="grid grid-cols-2 md:grid-cols-3 gap-3"
                   :class="hardwareInvalid ? 'ring-1 ring-red-400 rounded-xl p-2' : ''">
                <label v-for="art in ARTIKEL" :key="art.key"
                       class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                       :class="form.hardware.artikel[art.key as keyof typeof form.hardware.artikel]
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="checkbox" class="hidden"
                         v-model="form.hardware.artikel[art.key as keyof typeof form.hardware.artikel]" />
                  <span>{{ art.icon }}</span>
                  <span class="text-sm font-medium">{{ art.label }}</span>
                </label>
              </div>
              <p v-if="hardwareInvalid" class="text-xs text-red-500 mt-1">
                Bitte mindestens ein Hardware-Element auswählen.
              </p>
            </div>

            <!-- Monitor -->
            <div>
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Monitor</h3>
              <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition w-fit"
                     :class="form.hardware.monitor.benoetigt
                       ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                       : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                <input type="checkbox" class="hidden" v-model="form.hardware.monitor.benoetigt" />
                <span>🖥️</span>
                <span class="text-sm font-medium">Monitor benötigt</span>
              </label>
              <div v-if="form.hardware.monitor.benoetigt" class="mt-3 pl-4">
                <label class="label">Anzahl</label>
                <select v-model.number="form.hardware.monitor.anzahl" class="w-32 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm focus:outline-none">
                  <option :value="1">1</option>
                  <option :value="2">2</option>
                </select>
              </div>
            </div>

            <!-- Grund -->
            <div>
              <label class="label">Grund der Neubestellung *</label>
              <textarea v-model="form.hardware.grundBestellung"
                        :class="fieldClass('hardware.grundBestellung')"
                        rows="4" class="resize-none" />
            </div>
          </div>
        </template>

        <!-- Hardware – Neuer Mitarbeiter -->
        <template v-if="form.hardware.mitarbeiterTyp === 'Neuer Mitarbeiter'">
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-6">
            <h2 class="text-lg font-semibold text-[#3EAAB8]">💻 Hardwareausstattung</h2>

            <!-- Monitor -->
            <div>
              <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition w-fit"
                     :class="form.hardware.monitor.benoetigt
                       ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                       : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                <input type="checkbox" class="hidden" v-model="form.hardware.monitor.benoetigt" />
                <span>🖥️</span>
                <span class="text-sm font-medium">Monitor benötigt</span>
              </label>
              <div v-if="form.hardware.monitor.benoetigt" class="mt-3 pl-4">
                <label class="label">Anzahl</label>
                <select v-model.number="form.hardware.monitor.anzahl" class="w-32 rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm focus:outline-none">
                  <option :value="1">1</option>
                  <option :value="2">2</option>
                </select>
              </div>
            </div>

            <!-- Gerätetyp -->
            <div>
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Gerätetyp *</h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4"
                   :class="validationTriggered && isInvalid('hardware.geraet') ? 'ring-1 ring-red-400 rounded-xl p-1' : ''">
                <label v-for="g in [{ val: 'Laptop', icon: '💻', label: 'Laptop' }, { val: 'MiniPC', icon: '🖥️', label: 'Desktop (Mini-PC)' }]"
                       :key="g.val"
                       class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                       :class="form.hardware.geraet === g.val
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="radio" class="hidden" :value="g.val" v-model="form.hardware.geraet" />
                  <span>{{ g.icon }}</span>
                  <span class="text-sm font-medium">{{ g.label }}</span>
                </label>
              </div>
            </div>

            <!-- Dockingstation (nur bei Laptop) -->
            <div v-if="form.hardware.geraet === 'Laptop'">
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Dockingstation</h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                       :class="form.hardware.artikel.Dockingstation
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="radio" class="hidden" name="docking"
                         @change="form.hardware.artikel.Dockingstation = true; form.hardware.dockingVorhanden = false" />
                  <span>📦</span>
                  <span class="text-sm font-medium">Dockingstation bestellen</span>
                </label>
                <label class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                       :class="form.hardware.dockingVorhanden
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="radio" class="hidden" name="docking"
                         @change="form.hardware.dockingVorhanden = true; form.hardware.artikel.Dockingstation = false" />
                  <span>✅</span>
                  <span class="text-sm font-medium">Dockingstation vorhanden</span>
                </label>
              </div>
            </div>

            <!-- Peripherie -->
            <div>
              <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Peripherie</h3>
              <div class="grid grid-cols-2 md:grid-cols-3 gap-3"
                   :class="hardwareInvalid ? 'ring-1 ring-red-400 rounded-xl p-2' : ''">
                <label v-for="art in ARTIKEL.filter(a => !['Notebook','MiniPC','Dockingstation'].includes(a.key))"
                       :key="art.key"
                       class="flex items-center gap-3 p-4 rounded-xl border cursor-pointer transition"
                       :class="form.hardware.artikel[art.key as keyof typeof form.hardware.artikel]
                         ? 'ring-2 ring-[#3EAAB8] border-[#3EAAB8] bg-[#3EAAB8]/5'
                         : 'border-gray-200 dark:border-white/10 hover:bg-gray-50 dark:hover:bg-white/5'">
                  <input type="checkbox" class="hidden"
                         v-model="form.hardware.artikel[art.key as keyof typeof form.hardware.artikel]" />
                  <span>{{ art.icon }}</span>
                  <span class="text-sm font-medium">{{ art.label }}</span>
                </label>
              </div>
              <p v-if="hardwareInvalid" class="text-xs text-red-500 mt-1">
                Bitte mindestens ein Hardware-Element auswählen.
              </p>
            </div>

            <!-- Bemerkung -->
            <div>
              <label class="label">Optionale Bemerkung</label>
              <textarea v-model="form.hardware.bemerkung"
                        class="w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                               bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                               focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition resize-none"
                        rows="3" placeholder="z. B. Standort, Sonderwünsche, Hinweise …" />
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
.label { @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5; }
</style>