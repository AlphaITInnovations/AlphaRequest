<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'

const { showToast } = useToast()

interface AppUser {
  microsoft_id: string; display_name: string; email: string
  role: string; extra: string[]; last_login: string
}

const ROLE_PERMISSIONS: Record<string, string[]> = {
  none: [], viewer: ['view'], manager: ['view', 'manage'], admin: ['view', 'manage', 'admin'],
}
const ROLE_LABEL: Record<string, string> = { none: 'Kein Zugriff', viewer: 'Viewer', manager: 'Manager', admin: 'Admin' }
const ROLE_CLASS: Record<string, string> = {
  none:    'bg-gray-100 text-gray-500 dark:bg-white/5 dark:text-gray-400',
  viewer:  'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  manager: 'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  admin:   'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
}
const PERM_CLASS: Record<string, string> = {
  view:   'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  manage: 'bg-[#3EAAB8]/15 text-[#3EAAB8]',
  admin:  'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
}
function permClass(p: string) {
  if (p in PERM_CLASS) return PERM_CLASS[p]
  if (p.startsWith('create_')) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
  return 'bg-gray-100 text-gray-500 dark:bg-white/5 dark:text-gray-400'
}

const appUsers     = ref<AppUser[]>([])
const snapshot     = ref<Record<string, string>>({})
const loading      = ref(true)
const userSearch   = ref('')
const roleFilter   = ref('all')
const expandedUser = ref<string | null>(null)
const newPermInput = ref<Record<string, string>>({})

function serialize(u: AppUser): string {
  return JSON.stringify({ role: u.role, extra: [...u.extra].sort() })
}

const filteredAppUsers = computed(() => {
  let list = appUsers.value
  if (roleFilter.value !== 'all') list = list.filter(u => u.role === roleFilter.value)
  const q = userSearch.value.toLowerCase().trim()
  if (q) list = list.filter(u => u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
  return list
})

async function loadAppUsers() {
  loading.value = true
  try {
    await _loadAppUsers()
  } finally {
    loading.value = false
  }
}
async function _loadAppUsers() {
  const { data } = await client.get('/settings/app-users')
  const snap: Record<string, string> = {}
  appUsers.value = data.data.map((u: any) => {
    const rolePerms = ROLE_PERMISSIONS[u.role] ?? []
    const item: AppUser = {
      microsoft_id: u.microsoft_id, display_name: u.display_name, email: u.email,
      role: u.role, last_login: u.last_login,
      extra: (u.permissions ?? []).filter((p: string) => !rolePerms.includes(p)),
    }
    snap[item.microsoft_id] = serialize(item)
    newPermInput.value[item.microsoft_id] = ''
    return item
  })
  snapshot.value = snap
}

// Alle Änderungen NUR lokal – gespeichert wird über die Sticky-Bar.
function addExtra(u: AppUser) {
  const perm = (newPermInput.value[u.microsoft_id] || '').trim()
  if (!perm) return
  if (!u.extra.includes(perm)) u.extra.push(perm)
  newPermInput.value[u.microsoft_id] = ''
}
function removeExtra(u: AppUser, perm: string) { u.extra = u.extra.filter(p => p !== perm) }
function toggleExpand(id: string) { expandedUser.value = expandedUser.value === id ? null : id }

async function saveUsers() {
  const changed = appUsers.value.filter(u => serialize(u) !== snapshot.value[u.microsoft_id])
  if (changed.length === 0) return
  setSaving(true)
  try {
    for (const u of changed) {
      const prev = JSON.parse(snapshot.value[u.microsoft_id] || '{"role":"none","extra":[]}')
      if (u.role !== prev.role) {
        await client.patch(`/settings/app-users/${u.microsoft_id}/role`, { role: u.role })
      }
      const prevExtra: string[] = prev.extra ?? []
      for (const p of u.extra.filter(x => !prevExtra.includes(x))) {
        await client.patch(`/settings/app-users/${u.microsoft_id}/permissions/add`, { permission: p })
      }
      for (const p of prevExtra.filter((x: string) => !u.extra.includes(x))) {
        await client.patch(`/settings/app-users/${u.microsoft_id}/permissions/remove`, { permission: p })
      }
      snapshot.value[u.microsoft_id] = serialize(u)
    }
    showToast('Gespeichert', true)
  } catch {
    showToast('Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => appUsers.value.some(u => serialize(u) !== snapshot.value[u.microsoft_id]))
const { setSaving } = useSaver({ dirty, save: saveUsers, reset: () => loadAppUsers() })

onMounted(loadAppUsers)
</script>

<template>
  <section>
    <h2 class="section-title">Benutzer & Rollen</h2>
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
                px-4 py-3 text-sm text-blue-800 dark:text-blue-200 mb-4">
      Hier werden nur die Berechtigungen für die Übersicht <strong>„Alle Aufträge"</strong>
      (Ansehen / Verwalten / Admin) vergeben. Die Rechte zum <strong>Erstellen</strong> von Tickets
      legst du unter <strong>„Erstellrechte"</strong> fest.
    </div>
    <div class="card-section mb-4 space-y-2">
      <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Rollen & Permissions</p>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div class="rounded-xl border border-gray-200 dark:border-white/[0.06] p-3">
          <span class="text-xs font-medium px-2 py-0.5 rounded-full" :class="ROLE_CLASS.none">Kein Zugriff</span>
          <p class="text-gray-500 dark:text-gray-400 mt-2 text-xs">Keine Permissions</p>
        </div>
        <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 p-3">
          <span class="text-xs font-medium px-2 py-0.5 rounded-full" :class="ROLE_CLASS.viewer">Viewer</span>
          <p class="text-gray-500 dark:text-gray-400 mt-2 text-xs">view</p>
        </div>
        <div class="rounded-xl border border-[#3EAAB8]/30 p-3">
          <span class="text-xs font-medium px-2 py-0.5 rounded-full" :class="ROLE_CLASS.manager">Manager</span>
          <p class="text-gray-500 dark:text-gray-400 mt-2 text-xs">view · manage</p>
        </div>
        <div class="rounded-xl border border-purple-200 dark:border-purple-500/30 p-3">
          <span class="text-xs font-medium px-2 py-0.5 rounded-full" :class="ROLE_CLASS.admin">Admin</span>
          <p class="text-gray-500 dark:text-gray-400 mt-2 text-xs">view · manage · admin</p>
        </div>
      </div>
    </div>
    <div class="flex gap-3 mb-4">
      <input v-model="userSearch" placeholder="Name oder E-Mail suchen…" class="set-input flex-1" />
      <select v-model="roleFilter" class="set-input w-44">
        <option value="all">Alle Rollen</option>
        <option value="none">Kein Zugriff</option>
        <option value="viewer">Viewer</option>
        <option value="manager">Manager</option>
        <option value="admin">Admin</option>
      </select>
    </div>
    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <div v-else class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-gray-100 dark:border-white/[0.06] text-xs font-semibold text-gray-400 uppercase tracking-wider">
            <th class="px-5 py-3 text-left">Benutzer</th>
            <th class="px-5 py-3 text-left">E-Mail</th>
            <th class="px-5 py-3 text-left">Letzter Login</th>
            <th class="px-5 py-3 text-left">Rolle</th>
            <th class="px-5 py-3 text-left">Permissions</th>
            <th class="px-5 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <template v-for="u in filteredAppUsers" :key="u.microsoft_id">
            <tr class="hover:bg-gray-50 dark:hover:bg-[#263040] transition">
              <td class="px-5 py-3.5 font-medium text-gray-900 dark:text-white">{{ u.display_name }}</td>
              <td class="px-5 py-3.5 text-gray-500 dark:text-gray-400 text-xs">{{ u.email }}</td>
              <td class="px-5 py-3.5 text-gray-500 dark:text-gray-400 text-xs">
                {{ u.last_login ? new Date(u.last_login + 'Z').toLocaleString('de-DE') : '—' }}
              </td>
              <td class="px-5 py-3.5">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-medium px-2.5 py-1 rounded-full" :class="ROLE_CLASS[u.role] ?? ROLE_CLASS.none">
                    {{ ROLE_LABEL[u.role] ?? u.role }}
                  </span>
                  <select v-model="u.role"
                          class="text-xs rounded-lg border border-gray-200 dark:border-white/10
                                 bg-white dark:bg-[#263040] text-gray-700 dark:text-gray-300
                                 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-[#3EAAB8]/40">
                    <option value="none">Kein Zugriff</option>
                    <option value="viewer">Viewer</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
              </td>
              <td class="px-5 py-3.5">
                <div class="flex flex-wrap gap-1">
                  <span v-for="p in (ROLE_PERMISSIONS[u.role] ?? [])" :key="p"
                        class="text-xs px-2 py-0.5 rounded-full font-mono opacity-60" :class="permClass(p)">{{ p }}</span>
                  <span v-for="p in u.extra" :key="p"
                        class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-mono" :class="permClass(p)">
                    {{ p }}
                    <button @click="removeExtra(u, p)" class="hover:text-red-500 transition leading-none">✕</button>
                  </span>
                </div>
              </td>
              <td class="px-5 py-3.5">
                <button @click="toggleExpand(u.microsoft_id)" class="text-xs text-gray-400 hover:text-[#3EAAB8] transition">
                  {{ expandedUser === u.microsoft_id ? '▲ Schließen' : '▼ Permissions' }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedUser === u.microsoft_id" class="bg-gray-50 dark:bg-[#1C2535]">
              <td colspan="6" class="px-5 py-3">
                <div class="flex items-center gap-3 flex-wrap">
                  <span class="text-xs text-gray-500 dark:text-gray-400">Extra Permission hinzufügen:</span>
                  <input v-model="newPermInput[u.microsoft_id]" @keydown.enter.prevent="addExtra(u)"
                         placeholder="z. B. create_hardware" class="set-input text-xs py-1.5 w-56" />
                  <button @click="addExtra(u)" class="btn-primary text-xs py-1.5">Hinzufügen</button>
                  <span class="text-xs text-gray-400 italic">
                    Rollen-Permissions werden automatisch abgeleitet und können hier nicht entfernt werden.
                  </span>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="filteredAppUsers.length === 0">
            <td colspan="6" class="px-5 py-10 text-center text-sm text-gray-400 italic">Keine Benutzer gefunden</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
