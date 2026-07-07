<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { useDetailNav } from '@/composables/useDetailNav'
import SettingsList from '@/components/settings/SettingsList.vue'

const { showToast } = useToast()

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
const { selected, open, back } = useDetailNav(() => companies.value.length)

function mapCompany(c: any): CompanyItem {
  return {
    name: c?.name ?? '', pnr_from: c?.pnr_from ?? null, pnr_to: c?.pnr_to ?? null,
    mandant: c?.mandant ?? null, pnr_shared_with: c?.pnr_shared_with ?? null,
    pnr_current: c?.pnr_current ?? null, pnr_warned: !!c?.pnr_warned,
  }
}
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

function addCompany() {
  companies.value.push({ name: '', pnr_from: null, pnr_to: null, mandant: null,
                         pnr_shared_with: null, pnr_current: null, pnr_warned: false })
  open(companies.value.length - 1)
}
function removeCompany(idx: number) {
  const c = companies.value[idx]
  if (c.name && !confirm(`„${c.name}“ wirklich entfernen?`)) return
  companies.value.splice(idx, 1)
  back()
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
  setSaving(true)
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
    back()
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => serialize(companies.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save: saveCompanies, reset: () => loadCompanies() })

onMounted(loadCompanies)
</script>

<template>
  <section>
    <SettingsList v-if="selected === null" title="Firmen" :items="companies" :loading="loading"
                  add-label="+ Firma hinzufügen" search-placeholder="Firma suchen…"
                  empty-text="Noch keine Firmen vorhanden." :filter-text="(c) => c.name"
                  @add="addCompany" @select="open">
      <template #hint>
        <div class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20
                    px-4 py-3 text-sm text-amber-800 dark:text-amber-200 mb-3">
          Der Personalnummern-Bereich (Von/Bis) wird pro Firma vergeben; beim Onboarding entscheidet
          die „Firma lt.&nbsp;Arbeitsvertrag“, welche Nummer vergeben wird. Firmen können sich einen
          gemeinsamen Zähler teilen.
        </div>
      </template>
      <template #row="{ item }">
        <span class="flex-1 min-w-0 truncate font-medium text-gray-900 dark:text-white">{{ item.name || 'Unbenannt' }}</span>
        <span v-if="item.pnr_shared_with" class="text-xs px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] whitespace-nowrap">🔗 geteilt</span>
        <span v-else-if="freeCount(item) !== null" class="text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap" :class="freeBadgeClass(freeCount(item))">Frei: {{ freeCount(item) }}</span>
      </template>
    </SettingsList>

    <template v-else-if="companies[selected]">
      <div class="flex items-center justify-between mb-4">
        <button @click="back()" class="btn-secondary">← Zurück</button>
        <button @click="removeCompany(selected)"
                class="text-sm text-red-500 hover:text-red-600 hover:underline">Firma entfernen</button>
      </div>

      <div class="card-section space-y-3">
        <div>
          <label class="lbl">Firmenname</label>
          <input v-model="companies[selected].name" placeholder="Firmenname (z. B. AlphaConsult)" class="set-input w-full" />
        </div>
        <div>
          <label class="lbl">Personalnummern</label>
          <select v-model="companies[selected].pnr_shared_with" class="set-input w-full">
            <option :value="null">Eigener Nummernbereich</option>
            <option v-for="o in shareTargets(companies[selected])" :key="o.name" :value="o.name">
              Teilt Zähler mit „{{ o.name }}“
            </option>
          </select>
        </div>

        <div v-if="!companies[selected].pnr_shared_with" class="grid grid-cols-2 gap-3">
          <div>
            <label class="lbl">Personalnummer von</label>
            <input v-model="companies[selected].pnr_from"
                   @input="companies[selected].pnr_from = (companies[selected].pnr_from || '').replace(/\D/g, '')"
                   type="text" inputmode="numeric" class="set-input w-full" placeholder="00896" />
          </div>
          <div>
            <label class="lbl">Personalnummer bis</label>
            <input v-model="companies[selected].pnr_to"
                   @input="companies[selected].pnr_to = (companies[selected].pnr_to || '').replace(/\D/g, '')"
                   type="text" inputmode="numeric" class="set-input w-full" placeholder="15999" />
          </div>
        </div>

        <div>
          <label class="lbl">Mandantennr. <span class="text-gray-400 font-normal">(optional)</span></label>
          <input v-model="companies[selected].mandant" class="set-input w-full" placeholder="z. B. 100" />
        </div>

        <div v-if="companies[selected].pnr_shared_with" class="flex flex-wrap items-center gap-2 text-xs pt-1">
          <span class="px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] font-medium">
            🔗 Teilt Zähler mit „{{ companies[selected].pnr_shared_with }}“
          </span>
          <template v-if="sourceOf(companies[selected])">
            <span class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
              Aktuell: {{ currentDisplay(sourceOf(companies[selected])!) }}
            </span>
            <span class="px-2 py-0.5 rounded-full font-medium" :class="freeBadgeClass(freeCount(sourceOf(companies[selected])!))">
              Frei: {{ freeCount(sourceOf(companies[selected])!) }}
            </span>
          </template>
        </div>

        <div v-else-if="freeCount(companies[selected]) !== null" class="flex flex-wrap items-center gap-2 text-xs pt-1">
          <span class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
            Aktuell: {{ currentDisplay(companies[selected]) }}
          </span>
          <span class="px-2 py-0.5 rounded-full font-medium" :class="freeBadgeClass(freeCount(companies[selected]))">
            Frei: {{ freeCount(companies[selected]) }}
          </span>
          <span v-if="(freeCount(companies[selected]) ?? 0) === 0" class="text-red-600 dark:text-red-400">
            Bereich erschöpft – für diese Firma sind keine neuen Aufträge möglich.
          </span>
        </div>
      </div>
    </template>
  </section>
</template>
