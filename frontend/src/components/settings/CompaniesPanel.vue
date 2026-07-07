<script setup lang="ts">
import { ref, computed, watchEffect, onMounted, onUnmounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useSettingsSave, resetSettingsSave } from '@/composables/settingsSave'

const { showToast } = useToast()
const save = useSettingsSave()

interface CompanyItem {
  name: string
  pnr_from: string | null
  pnr_to: string | null
  mandant: string | null
  pnr_shared_with: string | null
  pnr_current: number | null
  pnr_warned: boolean
}
const companies = ref<CompanyItem[]>([])
const snapshot  = ref('')
const loading   = ref(true)

function mapCompany(c: any): CompanyItem {
  return {
    name: c?.name ?? '', pnr_from: c?.pnr_from ?? null, pnr_to: c?.pnr_to ?? null,
    mandant: c?.mandant ?? null, pnr_shared_with: c?.pnr_shared_with ?? null,
    pnr_current: c?.pnr_current ?? null, pnr_warned: !!c?.pnr_warned,
  }
}
// Nur die editierbaren Felder für den dirty-Vergleich.
function serialize(list: CompanyItem[]): string {
  return JSON.stringify(list.map(c => ({
    name: c.name, pnr_from: c.pnr_from, pnr_to: c.pnr_to,
    mandant: c.mandant, pnr_shared_with: c.pnr_shared_with,
  })))
}

async function loadCompanies() {
  loading.value = true
  try {
    const { data } = await client.get('/settings/companies')
    companies.value = (data.data.companies ?? []).map(mapCompany)
    snapshot.value = serialize(companies.value)
  } finally {
    loading.value = false
  }
}

function addCompanyRow() {
  companies.value.push({ name: '', pnr_from: null, pnr_to: null, mandant: null,
                         pnr_shared_with: null, pnr_current: null, pnr_warned: false })
}
function removeCompanyRow(idx: number) {
  const c = companies.value[idx]
  if (c.name && !confirm(`„${c.name}“ wirklich entfernen?`)) return
  companies.value.splice(idx, 1)
}

function shareTargets(c: CompanyItem): CompanyItem[] {
  return companies.value.filter(o =>
    o !== c && o.name.trim() && !o.pnr_shared_with && (o.pnr_from ?? '').trim() && (o.pnr_to ?? '').trim())
}
function sourceOf(c: CompanyItem): CompanyItem | null {
  if (!c.pnr_shared_with) return null
  return companies.value.find(o => o.name === c.pnr_shared_with) ?? null
}
function pnrWidth(c: CompanyItem): number {
  return Math.max((c.pnr_from ?? '').length, (c.pnr_to ?? '').length, 1)
}
function currentDisplay(c: CompanyItem): string {
  if (c.pnr_current == null) return '—'
  return String(c.pnr_current).padStart(pnrWidth(c), '0')
}
function freeCount(c: CompanyItem): number | null {
  const pf = (c.pnr_from ?? '').trim(), pt = (c.pnr_to ?? '').trim()
  if (!pf || !pt) return null
  const from = parseInt(pf, 10), to = parseInt(pt, 10)
  if (isNaN(from) || isNaN(to)) return null
  const base = c.pnr_current ?? (from - 1)
  return Math.max(0, to - base)
}
function freeBadgeClass(n: number | null): string {
  const v = n ?? 0
  return v === 0 ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
       : v <= 10 ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                 : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
}

async function saveCompanies() {
  for (const c of companies.value) {
    if (!c.name.trim()) { showToast('Jede Firma braucht einen Namen', false); return }
    if (c.pnr_shared_with) continue
    const pf = (c.pnr_from ?? '').trim(), pt = (c.pnr_to ?? '').trim()
    if (!!pf !== !!pt) { showToast(`„${c.name}“: Von und Bis bitte beide angeben`, false); return }
    if (pf && (!/^\d+$/.test(pf) || !/^\d+$/.test(pt))) {
      showToast(`„${c.name}“: Personalnummern dürfen nur Ziffern enthalten`, false); return
    }
    if (pf && parseInt(pf, 10) > parseInt(pt, 10)) {
      showToast(`„${c.name}“: „Von“ darf nicht größer als „Bis“ sein`, false); return
    }
  }
  save.saving = true
  try {
    const payload = companies.value.map(c => ({
      name: c.name.trim(),
      pnr_from: c.pnr_shared_with ? null : ((c.pnr_from ?? '').trim() || null),
      pnr_to:   c.pnr_shared_with ? null : ((c.pnr_to   ?? '').trim() || null),
      mandant:  (c.mandant ?? '').trim() || null,
      pnr_shared_with: c.pnr_shared_with || null,
    }))
    const { data } = await client.put('/settings/companies', { companies: payload })
    companies.value = (data.data.companies ?? []).map(mapCompany)
    snapshot.value = serialize(companies.value)
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || 'Fehler beim Speichern', false)
  } finally {
    save.saving = false
  }
}

const dirty = computed(() => serialize(companies.value) !== snapshot.value)
watchEffect(() => { save.dirty = dirty.value })
save.save  = saveCompanies
save.reset = () => { loadCompanies() }

onMounted(loadCompanies)
onUnmounted(() => resetSettingsSave(save))
</script>

<template>
  <section>
    <h2 class="section-title">Firmen</h2>
    <div class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20
                px-4 py-3 text-sm text-amber-800 dark:text-amber-200 mb-4">
      Der Personalnummern-Bereich
      (Von/Bis) wird pro Firma vergeben; beim Onboarding entscheidet die „Firma lt.&nbsp;Arbeitsvertrag“,
      welche Nummer vergeben wird. „Aktuell“ ist die zuletzt vergebene Nummer.
      Mehrere Firmen können sich einen gemeinsamen Zähler teilen – dazu bei einer Firma
      „Teilt Zähler mit …“ auswählen (statt eigenem Bereich).
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <div v-else class="space-y-4">
      <p v-if="companies.length === 0" class="text-sm text-gray-400 italic px-1">Noch keine Firmen vorhanden.</p>

      <div v-for="(c, i) in companies" :key="i"
           class="rounded-2xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#1A2130]
                  shadow-sm overflow-hidden">
        <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-200/80 dark:border-white/[0.08]
                    bg-white/70 dark:bg-white/[0.02]">
          <span class="flex-shrink-0 w-7 h-7 rounded-lg bg-[#3EAAB8]/15 text-[#3EAAB8] text-sm font-bold
                       flex items-center justify-center">{{ i + 1 }}</span>
          <input v-model="c.name" placeholder="Firmenname (z. B. AlphaConsult)"
                 class="flex-1 min-w-0 rounded-lg border border-transparent bg-transparent px-2 py-1
                        text-base font-semibold text-gray-900 dark:text-white placeholder-gray-400
                        hover:border-gray-200 dark:hover:border-white/10
                        focus:bg-white dark:focus:bg-[#263040] focus:border-[#3EAAB8]/50
                        focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/20 transition" />
          <button @click="removeCompanyRow(i)" title="Firma entfernen"
                  class="flex-shrink-0 w-8 h-8 rounded-lg text-gray-400 hover:text-red-500
                         hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center justify-center transition">✕</button>
        </div>

        <div class="p-4 space-y-3">
          <div>
            <label class="lbl">Personalnummern</label>
            <select v-model="c.pnr_shared_with" class="set-input w-full">
              <option :value="null">Eigener Nummernbereich</option>
              <option v-for="o in shareTargets(c)" :key="o.name" :value="o.name">Teilt Zähler mit „{{ o.name }}“</option>
            </select>
          </div>

          <div v-if="!c.pnr_shared_with" class="grid grid-cols-2 gap-3">
            <div>
              <label class="lbl">Personalnummer von</label>
              <input v-model="c.pnr_from" @input="c.pnr_from = (c.pnr_from || '').replace(/\D/g, '')"
                     type="text" inputmode="numeric" class="set-input w-full" placeholder="00896" />
            </div>
            <div>
              <label class="lbl">Personalnummer bis</label>
              <input v-model="c.pnr_to" @input="c.pnr_to = (c.pnr_to || '').replace(/\D/g, '')"
                     type="text" inputmode="numeric" class="set-input w-full" placeholder="15999" />
            </div>
          </div>

          <div>
            <label class="lbl">Mandantennr. <span class="text-gray-400 font-normal">(optional)</span></label>
            <input v-model="c.mandant" class="set-input w-full" placeholder="z. B. 100" />
          </div>

          <div v-if="c.pnr_shared_with" class="flex flex-wrap items-center gap-2 text-xs pt-1">
            <span class="px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] font-medium">
              🔗 Teilt Zähler mit „{{ c.pnr_shared_with }}“
            </span>
            <template v-if="sourceOf(c)">
              <span class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
                Aktuell: {{ currentDisplay(sourceOf(c)!) }}
              </span>
              <span class="px-2 py-0.5 rounded-full font-medium" :class="freeBadgeClass(freeCount(sourceOf(c)!))">
                Frei: {{ freeCount(sourceOf(c)!) }}
              </span>
            </template>
          </div>

          <div v-else-if="freeCount(c) !== null" class="flex flex-wrap items-center gap-2 text-xs pt-1">
            <span class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
              Aktuell: {{ currentDisplay(c) }}
            </span>
            <span class="px-2 py-0.5 rounded-full font-medium" :class="freeBadgeClass(freeCount(c))">
              Frei: {{ freeCount(c) }}
            </span>
            <span v-if="(freeCount(c) ?? 0) === 0" class="text-red-600 dark:text-red-400">
              Bereich erschöpft – für diese Firma sind keine neuen Aufträge möglich.
            </span>
          </div>
        </div>
      </div>

      <button @click="addCompanyRow" class="btn-secondary">+ Firma hinzufügen</button>
    </div>
  </section>
</template>
