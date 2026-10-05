<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { useDetailNav } from '@/composables/useDetailNav'
import { downloadJson, readJsonFile, dateStamp, extractList } from '@/lib/settingsTransfer'
import SettingsList from '@/components/settings/SettingsList.vue'
import CompanyDocumentsEditor from '@/components/settings/CompanyDocumentsEditor.vue'

const { showToast } = useToast()

interface CompanyItem {
  name: string
  pnr_from: string | null
  pnr_to: string | null
  mandant: string | null
  pnr_shared_with: string | null
  directus_firma_id: string | null
  domain: string | null
  documents_shared_with: string | null
  pnr_current: number | null
  pnr_warned: boolean
}
const companies = ref<CompanyItem[]>([])
const snapshot  = ref('')
const loading   = ref(true)
/** Serverseitig gespeicherte Firmennamen – nur für diese lassen sich Dokument-
 *  Vorlagen verwalten (sie hängen am Namen). Neu/umbenannt → erst speichern. */
const savedNames = ref<Set<string>>(new Set())
const { selected, open, back } = useDetailNav(() => companies.value.length)

function mapCompany(c: any): CompanyItem {
  // Text-Felder hart zu String|null zwingen: ein importiertes (ggf. handgeschriebenes)
  // JSON darf hier eine Zahl liefern (z. B. "pnr_from": 100) – sonst würfe
  // saveCompanies später bei (…).trim() eine unbehandelte Ausnahme (stiller Fehler).
  const s = (v: any): string | null => (v === null || v === undefined || v === '' ? null : String(v))
  return {
    name: c?.name == null ? '' : String(c.name),
    pnr_from: s(c?.pnr_from), pnr_to: s(c?.pnr_to),
    mandant: s(c?.mandant), pnr_shared_with: s(c?.pnr_shared_with),
    directus_firma_id: s(c?.directus_firma_id), domain: s(c?.domain),
    documents_shared_with: s(c?.documents_shared_with),
    pnr_current: typeof c?.pnr_current === 'number' ? c.pnr_current : null,
    pnr_warned: !!c?.pnr_warned,
  }
}
function serialize(list: CompanyItem[]): string {
  return JSON.stringify(list.map(c => ({
    name: c.name, pnr_from: c.pnr_from, pnr_to: c.pnr_to,
    mandant: c.mandant, pnr_shared_with: c.pnr_shared_with,
    directus_firma_id: c.directus_firma_id, domain: c.domain,
    documents_shared_with: c.documents_shared_with,
  })))
}

async function loadCompanies() {
  loading.value = true
  try {
    const { data } = await client.get('/settings/companies')
    companies.value = (data.data.companies ?? []).map(mapCompany)
    snapshot.value = serialize(companies.value)
    savedNames.value = new Set(companies.value.map(c => c.name))
  } finally {
    loading.value = false
  }
}

function addCompany() {
  companies.value.push({ name: '', pnr_from: null, pnr_to: null, mandant: null,
                         pnr_shared_with: null, directus_firma_id: null, domain: null,
                         documents_shared_with: null, pnr_current: null, pnr_warned: false })
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
/** Firmen, von denen Dokument-Vorlagen übernommen werden können: nicht man selbst,
 *  benannt und selbst keine Übernehmerin (keine Ketten). */
function docShareTargets(c: CompanyItem): CompanyItem[] {
  return companies.value.filter(o => o !== c && o.name.trim() && !o.documents_shared_with)
}
/** Übernimmt eine andere Firma die Vorlagen von c? Dann darf c nicht selbst übernehmen
 *  (würde eine verbotene Kette erzeugen). */
function isDocSource(c: CompanyItem): boolean {
  return companies.value.some(o => o !== c && o.documents_shared_with === c.name)
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
      directus_firma_id: (c.directus_firma_id ?? '').trim() || null,
      domain: (c.domain ?? '').trim().toLowerCase().replace(/^@/, '') || null,
      documents_shared_with: c.documents_shared_with || null,
    }))
    const { data } = await client.put('/settings/companies', { companies: payload })
    companies.value = (data.data.companies ?? []).map(mapCompany)
    snapshot.value = serialize(companies.value)
    savedNames.value = new Set(companies.value.map(c => c.name))
    back()
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.error?.message || e?.response?.data?.detail || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => serialize(companies.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save: saveCompanies, reset: () => loadCompanies() })

// ── Export / Import (JSON) ───────────────────────────────────────────────────
// Export lädt die aktuelle Liste als JSON herunter; Import ersetzt die bearbeitete
// Liste und überlässt die eigentliche Prüfung dem bestehenden „Speichern" (PUT).
const importInput = ref<HTMLInputElement | null>(null)

function exportCompanies() {
  downloadJson(`firmen-${dateStamp()}.json`, {
    kind: 'alpharequest:companies',
    version: 1,
    exportedAt: new Date().toISOString(),
    companies: companies.value.map(c => ({
      name: c.name, pnr_from: c.pnr_from, pnr_to: c.pnr_to, mandant: c.mandant,
      pnr_shared_with: c.pnr_shared_with, directus_firma_id: c.directus_firma_id,
      domain: c.domain, documents_shared_with: c.documents_shared_with,
    })),
  })
}

async function onImport(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''   // gleiche Datei erneut wählbar machen
  if (!file) return
  try {
    const list = extractList(await readJsonFile(file), 'companies', 'alpharequest:companies')
    if (!list.every(x => x && typeof x === 'object')) throw new Error('Unerwartetes Format der Firmen-Liste.')
    companies.value = list.map(mapCompany)
    back()
    showToast(`${companies.value.length} Firma(en) importiert – bitte prüfen und speichern.`, true)
  } catch (err: any) {
    showToast(err?.message || 'Import fehlgeschlagen.', false)
  }
}

onMounted(loadCompanies)
</script>

<template>
  <section>
    <SettingsList v-if="selected === null" title="Firmen" :items="companies" :loading="loading"
                  add-label="+ Firma hinzufügen" search-placeholder="Firma suchen…"
                  empty-text="Noch keine Firmen vorhanden." :filter-text="(c) => c.name"
                  @add="addCompany" @select="open">
      <template #actions>
        <button @click="exportCompanies" :disabled="loading || companies.length === 0" class="btn-secondary">Export</button>
        <button @click="importInput?.click()" :disabled="loading" class="btn-secondary">Import</button>
        <input ref="importInput" type="file" accept="application/json,.json" class="hidden" @change="onImport" />
      </template>
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

        <div>
          <label class="lbl">alphacore-Firmen-ID <span class="text-gray-400 font-normal">(optional)</span></label>
          <input v-model="companies[selected].directus_firma_id" class="set-input w-full"
                 placeholder="ID aus alphacore/Directus" />
          <p class="text-xs text-gray-400 mt-1">
            Wird beim automatischen Anlegen in Directus als Firmen-Fremdschlüssel geschrieben
            (Zuordnung „als alphacore-Firmen-ID auflösen“ in der Automation).
          </p>
        </div>

        <div>
          <label class="lbl">E-Mail-Domain <span class="text-gray-400 font-normal">(optional)</span></label>
          <input v-model="companies[selected].domain" class="set-input w-full"
                 placeholder="z. B. alpha-consult.de" />
          <p class="text-xs text-gray-400 mt-1">
            Basis der automatischen Firmenmail: vorname.nachname@domain.
          </p>
        </div>

        <div class="pt-1 border-t border-gray-100 dark:border-white/10 space-y-3">
          <div>
            <label class="lbl">Dokument-Vorlagen</label>
            <select v-model="companies[selected].documents_shared_with" class="set-input w-full"
                    :disabled="isDocSource(companies[selected])">
              <option :value="null">Eigene Vorlagen</option>
              <option v-for="o in docShareTargets(companies[selected])" :key="o.name" :value="o.name">
                Übernimmt Vorlagen von „{{ o.name }}“
              </option>
            </select>
            <p v-if="isDocSource(companies[selected])" class="text-xs text-gray-400 mt-1">
              Andere Firmen übernehmen die Vorlagen dieser Firma – sie kann daher nicht selbst übernehmen.
            </p>
            <p v-else class="text-xs text-gray-400 mt-1">
              Mehrere Firmen können sich dieselben Vorlagen teilen (z. B. ein gemeinsamer Arbeitsvertrag) –
              dann wird beim Erzeugen die Datei der gewählten Quelle gefüllt.
            </p>
          </div>
          <CompanyDocumentsEditor
            :company="savedNames.has(companies[selected].name.trim()) ? companies[selected].name.trim() : ''"
            :ready="!!companies[selected].name.trim() && savedNames.has(companies[selected].name.trim())"
            :shared-with="companies[selected].documents_shared_with" />
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
