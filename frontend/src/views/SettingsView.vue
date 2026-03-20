<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { client } from '@/api/client'
import { usersApi, type UserEntry } from '@/api/users'
import AppLayout from '@/components/AppLayout.vue'
import UserSelect from '@/components/UserSelect.vue'

// ── State ──────────────────────────────────────────────────────────────────────
type Section = 'general' | 'microsoft' | 'session' | 'companies' | 'groups' | 'permissions' | 'testmail' | 'personalnummer'
const active = ref<Section>('general')

const toast   = ref<{ msg: string; ok: boolean } | null>(null)
const users   = ref<UserEntry[]>([])

function showToast(msg: string, ok: boolean) {
  toast.value = { msg, ok }
  setTimeout(() => toast.value = null, 3000)
}

// ── ENV ────────────────────────────────────────────────────────────────────────
const env = ref<any>(null)
async function loadEnv() {
  const { data } = await client.get('/settings/env')
  env.value = data.data
}

// ── Companies ──────────────────────────────────────────────────────────────────
const companies    = ref<string[]>([])
const newCompany   = ref('')
async function loadCompanies() {
  const { data } = await client.get('/settings/companies')
  companies.value = data.data.companies
}
async function addCompany() {
  const v = newCompany.value.trim()
  if (!v) return
  if (companies.value.includes(v)) { showToast('Firma existiert bereits', false); return }
  const updated = [...companies.value, v]
  await saveCompanies(updated)
  newCompany.value = ''
}
async function removeCompany(idx: number) {
  if (!confirm(`"${companies.value[idx]}" wirklich löschen?`)) return
  await saveCompanies(companies.value.filter((_, i) => i !== idx))
}
async function saveCompanies(list: string[]) {
  try {
    const { data } = await client.put('/settings/companies', { companies: list })
    companies.value = data.data.companies
    showToast('Gespeichert', true)
  } catch { showToast('Fehler beim Speichern', false) }
}

// ── Permissions ────────────────────────────────────────────────────────────────
interface PermType { key: string; label: string; allowed_users: string[] }
const permissions  = ref<PermType[]>([])
const permSelected = ref<Record<string, { id: string; name: string } | null>>({})

async function loadPermissions() {
  const { data } = await client.get('/settings/permissions')
  permissions.value = data.data.types
  permissions.value.forEach(t => {
    permSelected.value[t.key] = null
  })
}
async function addPermUser(key: string) {
  const u = permSelected.value[key]
  if (!u) return
  const t = permissions.value.find(p => p.key === key)!
  if (!t.allowed_users.includes(u.id)) {
    t.allowed_users.push(u.id)
    await savePermissions()
  }
  permSelected.value[key] = null
}
async function removePermUser(key: string, id: string) {
  const t = permissions.value.find(p => p.key === key)!
  t.allowed_users = t.allowed_users.filter(x => x !== id)
  await savePermissions()
}
async function savePermissions() {
  const payload: Record<string, string[]> = {}
  permissions.value.forEach(t => { payload[t.key] = t.allowed_users })
  try {
    await client.put('/settings/permissions', { permissions: payload })
    showToast('Automatisch gespeichert', true)
  } catch { showToast('Fehler beim Speichern', false) }
}
function userName(id: string) {
  return users.value.find(u => u.id === id)?.displayName ?? id
}

// ── Groups ─────────────────────────────────────────────────────────────────────
interface Group { id: string; name: string; members: string[]; distributions: string[] }
const groups       = ref<Group[]>([])
const newGroupName = ref('')
const editGroup    = ref<Record<string, boolean>>({})
const editName     = ref<Record<string, string>>({})
const distInput    = ref<Record<string, string>>({})
const groupMember  = ref<Record<string, { id: string; name: string } | null>>({})

async function loadGroups() {
  const { data } = await client.get('/settings/groups')
  groups.value = data.data
  groups.value.forEach(g => {
    editGroup.value[g.id]   = false
    editName.value[g.id]    = g.name
    distInput.value[g.id]   = ''
    groupMember.value[g.id] = null
  })
}
async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  try {
    await client.post('/settings/groups', { name, distributions: [] })
    newGroupName.value = ''
    await loadGroups()
    showToast('Gruppe erstellt', true)
  } catch { showToast('Fehler beim Erstellen', false) }
}
async function saveGroupName(g: Group) {
  try {
    const { data } = await client.put(`/settings/groups/${g.id}`, {
      name: editName.value[g.id], members: g.members, distributions: g.distributions,
    })
    Object.assign(g, data.data)
    editGroup.value[g.id] = false
    showToast('Gespeichert', true)
  } catch { showToast('Fehler', false) }
}
async function deleteGroup(id: string) {
  if (!confirm('Gruppe löschen?')) return
  await client.delete(`/settings/groups/${id}`)
  await loadGroups()
  showToast('Gelöscht', true)
}
async function addMember(g: Group) {
  const m = groupMember.value[g.id]
  if (!m) return
  try {
    const { data } = await client.post(`/settings/groups/${g.id}/members`, { user_id: m.id })
    Object.assign(g, data.data)
    groupMember.value[g.id] = null
    showToast('Hinzugefügt', true)
  } catch { showToast('Fehler', false) }
}
async function removeMember(g: Group, uid: string) {
  const { data } = await client.delete(`/settings/groups/${g.id}/members/${uid}`)
  Object.assign(g, data.data)
}
async function addDistribution(g: Group) {
  const mail = distInput.value[g.id].trim().toLowerCase()
  if (!mail) return
  if (g.distributions.includes(mail)) { showToast('Existiert bereits', false); return }
  try {
    const { data } = await client.put(`/settings/groups/${g.id}`, {
      name: g.name, members: g.members, distributions: [...g.distributions, mail],
    })
    Object.assign(g, data.data)
    distInput.value[g.id] = ''
    showToast('Gespeichert', true)
  } catch { showToast('Fehler', false) }
}
async function removeDistribution(g: Group, mail: string) {
  const { data } = await client.put(`/settings/groups/${g.id}`, {
    name: g.name, members: g.members,
    distributions: g.distributions.filter(m => m !== mail),
  })
  Object.assign(g, data.data)
}

// ── Test Mail ──────────────────────────────────────────────────────────────────
const mailTo      = ref('')
const mailLoading = ref(false)
const mailResult  = ref<{ ok: boolean; msg: string } | null>(null)
async function sendTestMail() {
  if (!mailTo.value.trim()) return
  mailLoading.value = true
  mailResult.value  = null
  try {
    const { data } = await client.post('/settings/test-mail', { to: mailTo.value.trim() })
    mailResult.value = { ok: true, msg: data.data.message }
  } catch (e: any) {
    mailResult.value = { ok: false, msg: e.response?.data?.detail ?? 'Fehler' }
  } finally { mailLoading.value = false }
}

// ── Personalnummer ─────────────────────────────────────────────────────────────
const pnConfirm = ref('')
const pnLoading = ref(false)
const pnResult  = ref<{ ok: boolean; msg: string } | null>(null)
async function resetPersonalnummer() {
  if (pnConfirm.value !== 'RESET') return
  pnLoading.value = true
  pnResult.value  = null
  try {
    const { data } = await client.post('/settings/personalnummer/reset')
    pnResult.value = { ok: true, msg: data.data.message }
    pnConfirm.value = ''
  } catch (e: any) {
    pnResult.value = { ok: false, msg: e.response?.data?.detail ?? 'Fehler' }
  } finally { pnLoading.value = false }
}

// ── Init ───────────────────────────────────────────────────────────────────────
onMounted(async () => {
  const { data } = await usersApi.list()
  users.value = data.data.users
  await Promise.all([loadEnv(), loadCompanies(), loadPermissions(), loadGroups()])
})

// ── Nav ────────────────────────────────────────────────────────────────────────
const nav = [
  { key: 'general',       label: 'Allgemein',           group: 'System' },
  { key: 'microsoft',     label: 'Microsoft OAuth',      group: 'System' },
  { key: 'session',       label: 'Session & Security',   group: 'System' },
  { key: 'companies',     label: 'Firmen',               group: 'Organisation' },
  { key: 'groups',        label: 'Fachabteilungen',      group: 'Organisation' },
  { key: 'permissions',   label: 'Auftragstypen',        group: 'Berechtigungen' },
  { key: 'testmail',      label: 'Testmail',             group: 'Kommunikation' },
  { key: 'personalnummer',label: 'Personalnummer Reset', group: 'Tools' },
] as const

const navGroups = computed(() => {
  const groups: Record<string, typeof nav[number][]> = {}
  nav.forEach(n => { (groups[n.group] ??= []).push(n) })
  return groups
})
</script>

<template>
  <AppLayout title="Admin · Settings">

    <!-- Toast -->
    <Transition enter-active-class="transition duration-200" enter-from-class="opacity-0 translate-y-2"
                leave-active-class="transition duration-150" leave-to-class="opacity-0">
      <div v-if="toast"
           class="fixed top-6 right-6 z-50 rounded-xl border px-4 py-3 text-sm shadow-lg"
           :class="toast.ok
             ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
             : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
        {{ toast.msg }}
      </div>
    </Transition>

    <div class="flex gap-5 min-h-[600px]">

      <!-- ── Sidebar ── -->
      <aside class="w-56 flex-shrink-0">
        <nav class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-3 space-y-4 sticky top-4">
          <template v-for="(items, group) in navGroups" :key="group">
            <div>
              <p class="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-gray-400">
                {{ group }}
              </p>
              <button
                v-for="item in items" :key="item.key"
                @click="active = item.key as Section"
                class="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition text-left"
                :class="active === item.key
                  ? 'bg-[#3EAAB8] text-white font-medium'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'"
              >
                {{ item.label }}
              </button>
            </div>
          </template>
        </nav>
      </aside>

      <!-- ── Content ── -->
      <div class="flex-1 min-w-0 space-y-6">

        <!-- ENV Info Banner -->
        <div v-if="['general','microsoft','session'].includes(active)"
             class="rounded-xl border border-blue-200 dark:border-blue-500/30
                    bg-blue-50 dark:bg-blue-900/20 px-4 py-3 text-sm
                    text-blue-800 dark:text-blue-200">
          Diese Einstellungen werden über <strong>Umgebungsvariablen</strong> (.env) verwaltet und können hier nur eingesehen werden.
        </div>

        <!-- ── Allgemein ── -->
        <section v-if="active === 'general'">
          <h2 class="section-title">Allgemein</h2>
          <div class="card-section" v-if="env">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-400 border-b dark:border-white/[0.06]">
                <th class="pb-2 pr-4">Variable</th><th class="pb-2 pr-4">Beschreibung</th><th class="pb-2">Wert</th>
              </tr></thead>
              <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                <tr v-for="(val, key) in env.general" :key="key" class="text-sm">
                  <td class="py-2.5 pr-4 font-mono text-xs text-gray-600 dark:text-gray-400">{{ key }}</td>
                  <td class="py-2.5 pr-4 text-gray-600 dark:text-gray-400">{{ envDesc(key) }}</td>
                  <td class="py-2.5 font-medium text-gray-900 dark:text-white">{{ val.value }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- ── Microsoft ── -->
        <section v-if="active === 'microsoft'">
          <h2 class="section-title">Microsoft OAuth</h2>
          <div class="card-section" v-if="env">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-400 border-b dark:border-white/[0.06]">
                <th class="pb-2 pr-4">Variable</th><th class="pb-2 pr-4">Beschreibung</th><th class="pb-2">Status</th>
              </tr></thead>
              <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                <tr v-for="(val, key) in env.microsoft" :key="key">
                  <td class="py-2.5 pr-4 font-mono text-xs text-gray-600 dark:text-gray-400">{{ key }}</td>
                  <td class="py-2.5 pr-4 text-gray-600 dark:text-gray-400">{{ envDesc(key) }}</td>
                  <td class="py-2.5">
                    <span v-if="val.sensitive"
                          class="text-xs px-2 py-0.5 rounded-full font-medium"
                          :class="val.is_set
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                            : 'bg-gray-100 text-gray-500 dark:bg-white/5'">
                      {{ val.is_set ? 'gesetzt' : '—' }}
                    </span>
                    <span v-else class="font-medium text-gray-900 dark:text-white">{{ val.value }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- ── Session ── -->
        <section v-if="active === 'session'">
          <h2 class="section-title">Session & Security</h2>
          <div class="card-section" v-if="env">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-400 border-b dark:border-white/[0.06]">
                <th class="pb-2 pr-4">Variable</th><th class="pb-2 pr-4">Beschreibung</th><th class="pb-2">Status</th>
              </tr></thead>
              <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
                <tr v-for="(val, key) in env.session" :key="key">
                  <td class="py-2.5 pr-4 font-mono text-xs text-gray-600 dark:text-gray-400">{{ key }}</td>
                  <td class="py-2.5 pr-4 text-gray-600 dark:text-gray-400">{{ envDesc(key) }}</td>
                  <td class="py-2.5">
                    <span v-if="val.sensitive"
                          class="text-xs px-2 py-0.5 rounded-full font-medium"
                          :class="val.is_set
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                            : 'bg-gray-100 text-gray-500'">
                      {{ val.is_set ? 'gesetzt' : '—' }}
                    </span>
                    <span v-else class="font-medium text-gray-900 dark:text-white">{{ val.value }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- ── Firmen ── -->
        <section v-if="active === 'companies'">
          <h2 class="section-title">Firmen</h2>
          <div class="rounded-xl border border-amber-200 dark:border-amber-500/30
                      bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm
                      text-amber-800 dark:text-amber-200 mb-4">
            Firmen müssen exakt so wie im Drop-Down in NinjaOne heißen.
          </div>
          <div class="card-section space-y-4">
            <div class="flex gap-3">
              <input v-model="newCompany" @keydown.enter.prevent="addCompany"
                     placeholder="Neue Firma…" class="input flex-1" />
              <button @click="addCompany" class="btn-primary">Hinzufügen</button>
            </div>
            <div v-if="companies.length === 0" class="text-sm text-gray-400 italic">Noch keine Firmen vorhanden.</div>
            <ul class="flex flex-wrap gap-2">
              <li v-for="(c, i) in companies" :key="c"
                  class="inline-flex items-center gap-2 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm">
                {{ c }}
                <button @click="removeCompany(i)" class="hover:text-red-500 transition">✕</button>
              </li>
            </ul>
          </div>
        </section>

        <!-- ── Permissions ── -->
        <section v-if="active === 'permissions'">
          <div class="flex items-center justify-between mb-4">
            <h2 class="section-title mb-0">Auftragstypen</h2>
            <span class="text-xs text-gray-400">Änderungen werden automatisch gespeichert</span>
          </div>
          <div class="space-y-6">
            <div v-for="t in permissions" :key="t.key"
                 class="card-section space-y-3">
              <div class="flex items-center justify-between">
                <h3 class="font-semibold text-gray-900 dark:text-white">{{ t.label }}</h3>
                <span class="font-mono text-xs text-gray-400">{{ t.key }}</span>
              </div>
              <div v-if="t.allowed_users.length === 0"
                   class="text-xs rounded-lg border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20
                          text-amber-700 dark:text-amber-300 px-3 py-2">
                ⚠ Niemand darf diesen Auftragstyp erstellen
              </div>
              <div class="flex flex-wrap gap-2">
                <span v-for="id in t.allowed_users" :key="id"
                      class="inline-flex items-center gap-1.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm">
                  {{ userName(id) }}
                  <button @click="removePermUser(t.key, id)" class="hover:text-red-500 transition">✕</button>
                </span>
              </div>
              <div class="flex gap-2">
                <UserSelect
                  label=""
                  placeholder="Benutzer hinzufügen…"
                  :model-value="permSelected[t.key]"
                  @update:model-value="permSelected[t.key] = $event"
                  class="flex-1"
                />
                <button @click="addPermUser(t.key)" class="btn-primary self-end">+</button>
              </div>
            </div>
          </div>
        </section>

        <!-- ── Gruppen ── -->
        <section v-if="active === 'groups'">
          <h2 class="section-title">Fachabteilungen</h2>
          <div class="card-section mb-4 flex gap-3">
            <input v-model="newGroupName" @keydown.enter.prevent="createGroup"
                   placeholder="Neue Gruppe…" class="input flex-1" />
            <button @click="createGroup" class="btn-primary">Erstellen</button>
          </div>
          <div class="space-y-4">
            <div v-for="g in groups" :key="g.id"
                 class="card-section space-y-5">
              <!-- Header -->
              <div class="flex items-center justify-between">
                <div>
                  <h3 v-if="!editGroup[g.id]" class="text-lg font-semibold text-gray-900 dark:text-white">{{ g.name }}</h3>
                  <input v-else v-model="editName[g.id]" class="input w-72" />
                </div>
                <div class="flex items-center gap-2">
                  <button v-if="!editGroup[g.id]" @click="editGroup[g.id] = true"
                          class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-white/5 transition text-gray-500">✏️</button>
                  <button v-if="editGroup[g.id]" @click="saveGroupName(g)"
                          class="p-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white transition">✓</button>
                  <button v-if="editGroup[g.id]" @click="editGroup[g.id] = false"
                          class="p-2 rounded-xl bg-gray-400 hover:bg-gray-500 text-white transition">✕</button>
                  <button @click="deleteGroup(g.id)"
                          class="p-2 rounded-xl hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500 transition">🗑</button>
                </div>
              </div>

              <div class="grid md:grid-cols-2 gap-6">
                <!-- Mitglieder -->
                <div class="space-y-3">
                  <div class="flex items-center justify-between">
                    <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Mitglieder</p>
                    <span class="text-xs text-gray-400">{{ g.members.length }} Benutzer</span>
                  </div>
                  <div class="flex flex-wrap gap-2 min-h-[36px]">
                    <span v-for="uid in g.members" :key="uid"
                          class="inline-flex items-center gap-1.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm">
                      {{ userName(uid) }}
                      <button @click="removeMember(g, uid)" class="hover:text-red-500 transition">✕</button>
                    </span>
                  </div>
                  <div class="flex gap-2">
                    <UserSelect
                      label=""
                      placeholder="Benutzer hinzufügen…"
                      :model-value="groupMember[g.id]"
                      @update:model-value="groupMember[g.id] = $event"
                      class="flex-1"
                    />
                    <button @click="addMember(g)"
                            class="btn-primary self-end">+</button>
                  </div>
                </div>

                <!-- Verteiler -->
                <div class="space-y-3">
                  <div class="flex items-center justify-between">
                    <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Verteiler (E-Mail)</p>
                    <span class="text-xs text-gray-400">{{ g.distributions.length }} Adressen</span>
                  </div>
                  <div class="flex flex-wrap gap-2 min-h-[36px]">
                    <span v-for="mail in g.distributions" :key="mail"
                          class="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 dark:bg-emerald-900/20
                                 text-emerald-700 dark:text-emerald-300 px-3 py-1 text-sm">
                      {{ mail }}
                      <button @click="removeDistribution(g, mail)" class="hover:text-red-500 transition">✕</button>
                    </span>
                  </div>
                  <div class="flex gap-2">
                    <input v-model="distInput[g.id]" @keydown.enter.prevent="addDistribution(g)"
                           type="email" placeholder="Neue Verteiler-Mail…" class="input flex-1" />
                    <button @click="addDistribution(g)"
                            class="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm transition">+</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ── Testmail ── -->
        <section v-if="active === 'testmail'">
          <h2 class="section-title">Testmail</h2>
          <div class="card-section space-y-4">
            <div class="flex gap-3">
              <input v-model="mailTo" type="email" placeholder="empfaenger@firma.de" class="input flex-1" />
              <button @click="sendTestMail" :disabled="mailLoading" class="btn-primary disabled:opacity-60">
                {{ mailLoading ? 'Sende…' : 'Senden' }}
              </button>
            </div>
            <div v-if="mailResult" class="rounded-xl border px-4 py-3 text-sm"
                 :class="mailResult.ok
                   ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
                   : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
              {{ mailResult.msg }}
            </div>
          </div>
        </section>

        <!-- ── Personalnummer ── -->
        <section v-if="active === 'personalnummer'">
          <h2 class="section-title">Personalnummer zurücksetzen</h2>
          <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-200 mb-4">
            ⚠️ <strong>ACHTUNG:</strong> Diese Aktion setzt den globalen Personalnummerzähler zurück und kann nicht rückgängig gemacht werden.
          </div>
          <div class="card-section space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Zur Bestätigung <span class="font-mono font-bold">RESET</span> eingeben:
              </label>
              <input v-model="pnConfirm" placeholder="RESET" class="input w-64" />
            </div>
            <button @click="resetPersonalnummer"
                    :disabled="pnLoading || pnConfirm !== 'RESET'"
                    class="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-sm font-medium
                           transition disabled:opacity-50 disabled:cursor-not-allowed">
              {{ pnLoading ? 'Wird zurückgesetzt…' : 'Personalnummer zurücksetzen' }}
            </button>
            <div v-if="pnResult" class="rounded-xl border px-4 py-3 text-sm"
                 :class="pnResult.ok
                   ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
                   : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
              {{ pnResult.msg }}
            </div>
          </div>
        </section>

      </div>
    </div>
  </AppLayout>
</template>

<script lang="ts">
// ENV Beschreibungen
const ENV_DESCS: Record<string, string> = {
  APP_ENV: 'Laufzeitumgebung (z. B. development/production)',
  PORT: 'HTTP-Port, auf dem die App lauscht',
  HTTPS: 'Aktiviert HTTPS',
  TICKET_MAIL: 'Fallback-Mailbox für Benachrichtigungen',
  CLIENT_ID: 'App-Registrierung (öffentliche ID)',
  CLIENT_SECRET: 'App-Geheimnis (niemals anzeigen)',
  TENANT_ID: 'Azure AD-Tenant',
  REDIRECT_URI: 'OAuth-Redirect für Microsoft-Login',
  SCOPE: 'Gewünschte Microsoft-Scopes',
  ADMIN_GROUP_ID: 'Azure-Gruppe mit Admin-Zugriff',
  SESSION_TIMEOUT: 'Inaktivitäts-Timeout der Sitzung (Sek.)',
  SECRET_KEY: 'Signierschlüssel für Session/Cookies',
}
function envDesc(key: string) { return ENV_DESCS[key] ?? key }
</script>

<style scoped>
@reference "../style.css";
.section-title { @apply text-lg font-semibold text-gray-900 dark:text-white mb-4; }
.card-section  { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-5; }
.input         { @apply rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition; }
.btn-primary   { @apply px-4 py-2 rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white text-sm font-medium transition; }
</style>