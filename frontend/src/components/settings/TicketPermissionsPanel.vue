<script setup lang="ts">
import { ref, computed, watchEffect, onMounted, onUnmounted } from 'vue'
import { client } from '@/api/client'
import { usersApi, type UserEntry } from '@/api/users'
import UserSelect from '@/components/UserSelect.vue'
import { useSettingsSave, resetSettingsSave } from '@/composables/settingsSave'

const save = useSettingsSave()

interface PermType { key: string; label: string; allowed_users: string[]; allowed_groups: string[] }
interface AdGroup { id: string; displayName: string; description: string }
interface Group { id: string; name: string }

const EVERYONE = '__everyone__'

const permissions  = ref<PermType[]>([])
const snapshot     = ref('')
const loading      = ref(true)
const permSelected = ref<Record<string, { id: string; name: string } | null>>({})
const adGroups     = ref<AdGroup[]>([])
const adGroupSearch = ref<Record<string, string>>({})
const adGroupOpen   = ref<Record<string, boolean>>({})
const groups = ref<Group[]>([])
const users  = ref<UserEntry[]>([])

function serialize(list: PermType[]): string {
  return JSON.stringify(list.map(t => ({ key: t.key, u: [...t.allowed_users].sort(), g: [...t.allowed_groups].sort() })))
}

async function loadAll() {
  loading.value = true
  try {
    const [perms, ad, grp, usr] = await Promise.all([
      client.get('/settings/permissions'),
      client.get('/settings/ad-groups').catch(() => ({ data: { data: [] } })),
      client.get('/settings/groups'),
      usersApi.list(),
    ])
    permissions.value = perms.data.data.types
    permissions.value.forEach(t => {
      permSelected.value[t.key] = null
      adGroupSearch.value[t.key] = ''
      adGroupOpen.value[t.key]   = false
    })
    adGroups.value = ad.data.data
    groups.value   = grp.data.data
    users.value    = usr.data.data.users
    snapshot.value = serialize(permissions.value)
  } finally {
    loading.value = false
  }
}

type GroupKind = 'everyone' | 'fach' | 'ad' | 'unknown'
function groupKind(id: string): GroupKind {
  if (id === EVERYONE) return 'everyone'
  if (groups.value.some(g => g.id === id)) return 'fach'
  if (adGroups.value.some(g => g.id === id)) return 'ad'
  return 'unknown'
}
function groupLabel(id: string): string {
  if (id === EVERYONE) return 'Jeder (alle eingeloggten Nutzer)'
  return groups.value.find(g => g.id === id)?.name
      ?? adGroups.value.find(g => g.id === id)?.displayName ?? id
}
function groupIcon(id: string): string {
  return { everyone: '🌐', fach: '🏢', ad: '👥', unknown: '❔' }[groupKind(id)]
}
function userName(id: string) { return users.value.find(u => u.id === id)?.displayName ?? id }

function filteredAdGroups(key: string): AdGroup[] {
  const t = permissions.value.find(p => p.key === key)
  const already = new Set(t?.allowed_groups ?? [])
  const q = (adGroupSearch.value[key] ?? '').toLowerCase().trim()
  return adGroups.value.filter(g => !already.has(g.id)).filter(g => !q || g.displayName.toLowerCase().includes(q))
}

// Alle Änderungen NUR lokal – gespeichert wird über die Sticky-Bar.
function addPermEntity(key: string) {
  const sel = permSelected.value[key]
  if (!sel) return
  const t = permissions.value.find(p => p.key === key)!
  const isFach = groups.value.some(g => g.id === sel.id)
  if (isFach) { if (!t.allowed_groups.includes(sel.id)) t.allowed_groups.push(sel.id) }
  else        { if (!t.allowed_users.includes(sel.id))  t.allowed_users.push(sel.id) }
  permSelected.value[key] = null
}
function removePermUser(key: string, id: string) {
  const t = permissions.value.find(p => p.key === key)!
  t.allowed_users = t.allowed_users.filter(x => x !== id)
}
function addPermGroup(key: string, groupId: string) {
  const t = permissions.value.find(p => p.key === key)!
  if (!t.allowed_groups.includes(groupId)) t.allowed_groups.push(groupId)
  adGroupSearch.value[key] = ''
}
function removePermGroup(key: string, groupId: string) {
  const t = permissions.value.find(p => p.key === key)!
  t.allowed_groups = t.allowed_groups.filter(x => x !== groupId)
}

async function savePermissions() {
  const userPayload: Record<string, string[]> = {}
  const groupPayload: Record<string, string[]> = {}
  permissions.value.forEach(t => { userPayload[t.key] = t.allowed_users; groupPayload[t.key] = t.allowed_groups })
  save.saving = true
  try {
    await client.put('/settings/permissions', { permissions: userPayload, group_permissions: groupPayload })
    snapshot.value = serialize(permissions.value)
  } finally {
    save.saving = false
  }
}

const dirty = computed(() => serialize(permissions.value) !== snapshot.value)
watchEffect(() => { save.dirty = dirty.value })
save.save  = savePermissions
save.reset = () => { loadAll() }

onMounted(loadAll)
onUnmounted(() => resetSettingsSave(save))
</script>

<template>
  <section>
    <h2 class="section-title">Erstellrechte</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
      Lege je Auftragstyp fest, wer ihn erstellen darf – <strong>Jeder</strong>, einzelne
      <strong>Personen</strong>, <strong>Fachabteilungen</strong> oder <strong>AD-Gruppen</strong>.
    </p>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <div v-else class="space-y-4">
      <div v-for="t in permissions" :key="t.key" class="card-section space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="font-semibold text-gray-900 dark:text-white">{{ t.label }}</h3>
          <span class="font-mono text-xs text-gray-400">{{ t.key }}</span>
        </div>

        <div class="flex flex-wrap gap-2 items-center min-h-[44px] rounded-xl
                    border border-gray-100 dark:border-white/[0.06] bg-gray-50/60 dark:bg-white/[0.02] p-2.5">
          <span v-if="t.allowed_groups.length === 0 && t.allowed_users.length === 0"
                class="text-xs font-medium text-amber-700 dark:text-amber-300">
            ⚠ Niemand darf diesen Auftragstyp erstellen
          </span>
          <span v-for="gid in t.allowed_groups" :key="'g-' + gid"
                class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium"
                :class="{
                  'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300': groupKind(gid) === 'everyone',
                  'bg-[#3EAAB8]/10 text-[#3EAAB8]':                                                  groupKind(gid) === 'fach',
                  'bg-purple-100 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300':        groupKind(gid) === 'ad',
                  'bg-gray-100 dark:bg-white/10 text-gray-500':                                      groupKind(gid) === 'unknown',
                }">
            <span>{{ groupIcon(gid) }}</span>{{ groupLabel(gid) }}
            <button @click="removePermGroup(t.key, gid)" class="hover:text-red-500 transition">✕</button>
          </span>
          <span v-for="id in t.allowed_users" :key="'u-' + id"
                class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium
                       bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300">
            👤 {{ userName(id) }}
            <button @click="removePermUser(t.key, id)" class="hover:text-red-500 transition">✕</button>
          </span>
        </div>

        <p v-if="t.allowed_groups.includes(EVERYONE)" class="text-xs text-emerald-700 dark:text-emerald-300">
          🌐 Jeder eingeloggte Nutzer darf erstellen – weitere Einträge sind nicht nötig.
        </p>

        <div v-else class="flex flex-col lg:flex-row gap-2 lg:items-start">
          <div class="flex gap-2 flex-1 min-w-0">
            <UserSelect label="" placeholder="Person oder Fachabteilung…" :show-groups="true"
                        :model-value="permSelected[t.key]"
                        @update:model-value="permSelected[t.key] = $event" class="flex-1 min-w-0" />
            <button @click="addPermEntity(t.key)" class="btn-primary self-end whitespace-nowrap">+ Hinzufügen</button>
          </div>
          <div class="relative lg:w-60">
            <input v-model="adGroupSearch[t.key]" placeholder="AD-Gruppe…" class="set-input w-full"
                   @focus="adGroupOpen[t.key] = true"
                   @blur="adGroupOpen[t.key] = false; adGroupSearch[t.key] = ''" />
            <div v-if="adGroupOpen[t.key] && adGroupSearch[t.key]?.length > 0 && filteredAdGroups(t.key).length > 0"
                 class="absolute z-20 mt-1 w-full max-h-48 overflow-y-auto rounded-xl border border-gray-200
                        dark:border-white/10 bg-white dark:bg-[#263040] shadow-lg">
              <button v-for="g in filteredAdGroups(t.key).slice(0, 15)" :key="g.id"
                      @mousedown.prevent="addPermGroup(t.key, g.id)"
                      class="w-full text-left px-3.5 py-2.5 text-sm hover:bg-purple-500/10 transition
                             text-gray-900 dark:text-gray-100 flex items-center justify-between">
                <span>{{ g.displayName }}</span>
                <span v-if="g.description" class="text-xs text-gray-400 ml-2 truncate max-w-[160px]">{{ g.description }}</span>
              </button>
            </div>
          </div>
          <button @click="addPermGroup(t.key, EVERYONE)"
                  class="px-3 py-2 rounded-xl text-sm font-medium whitespace-nowrap self-end
                         border border-emerald-300/60 text-emerald-700 dark:text-emerald-300
                         bg-emerald-50 dark:bg-emerald-900/20 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition">
            🌐 Jeder
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
