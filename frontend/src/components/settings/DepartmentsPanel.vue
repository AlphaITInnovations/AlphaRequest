<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { client } from '@/api/client'
import { usersApi, type UserEntry } from '@/api/users'
import UserSelect from '@/components/UserSelect.vue'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'
import { useDetailNav } from '@/composables/useDetailNav'
import SettingsList from '@/components/settings/SettingsList.vue'

const { showToast } = useToast()

interface Group { id: string; name: string; members: string[]; distributions: string[]; required?: boolean; hidden?: boolean }

const groups   = ref<Group[]>([])
const snapshot = ref('')
const users    = ref<UserEntry[]>([])
const loading  = ref(true)
const { selected, open, back } = useDetailNav(() => groups.value.length)
const memberSel = ref<{ id: string; name: string } | null>(null)
const distInput = ref('')
let tmpSeq = 0

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

watch(selected, () => { memberSel.value = null; distInput.value = '' })

function serialize(list: Group[]): string {
  return JSON.stringify(list.map(g => ({
    name: g.name, members: [...g.members].sort(), distributions: [...g.distributions].sort(), hidden: !!g.hidden,
  })))
}
function userName(id: string) { return users.value.find(u => u.id === id)?.displayName ?? id }

async function loadGroups() {
  loading.value = true
  try {
    const [grp, usr] = await Promise.all([client.get('/settings/groups'), usersApi.list()])
    groups.value = grp.data.data
    users.value  = usr.data.data.users
    snapshot.value = serialize(groups.value)
  } finally {
    loading.value = false
  }
}

function addGroup() {
  groups.value.push({ id: `tmp_${++tmpSeq}`, name: '', members: [], distributions: [], required: false, hidden: false })
  open(groups.value.length - 1)
}
function removeGroup(idx: number) {
  const g = groups.value[idx]
  if (g.required) return
  if (g.name && !confirm(`Fachabteilung „${g.name}“ wirklich löschen? (wird beim Speichern übernommen)`)) return
  groups.value.splice(idx, 1)
  back()
}

function addMember() {
  const g = selected.value !== null ? groups.value[selected.value] : null
  if (!g || !memberSel.value) return
  if (!g.members.includes(memberSel.value.id)) g.members.push(memberSel.value.id)
  memberSel.value = null
}
function removeMember(g: Group, uid: string) { g.members = g.members.filter(m => m !== uid) }
function addDistribution() {
  const g = selected.value !== null ? groups.value[selected.value] : null
  if (!g) return
  const mail = distInput.value.trim().toLowerCase()
  if (!mail) return
  if (!EMAIL_RE.test(mail)) { showToast('Ungültige E-Mail', false); return }
  if (g.distributions.includes(mail)) { showToast('Existiert bereits', false); return }
  g.distributions.push(mail)
  distInput.value = ''
}
function removeDistribution(g: Group, mail: string) { g.distributions = g.distributions.filter(m => m !== mail) }

async function saveGroups() {
  if (groups.value.some(g => !g.name.trim())) { showToast('Jede Fachabteilung braucht einen Namen', false); return }
  setSaving(true)
  try {
    const payload = groups.value.map(g => ({
      id: (g.id && String(g.id).startsWith('tmp_')) ? null : g.id,
      name: g.name.trim(), members: g.members, distributions: g.distributions, hidden: !!g.hidden,
    }))
    const { data } = await client.put('/settings/groups', { groups: payload })
    groups.value = data.data
    snapshot.value = serialize(groups.value)
    back()
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => serialize(groups.value) !== snapshot.value)
const { setSaving } = useSaver({ dirty, save: saveGroups, reset: () => loadGroups() })

onMounted(loadGroups)
</script>

<template>
  <section>
    <SettingsList v-if="selected === null" title="Fachabteilungen" :items="groups" :loading="loading"
                  add-label="+ Fachabteilung hinzufügen" search-placeholder="Fachabteilung suchen…"
                  empty-text="Noch keine Fachabteilungen." :filter-text="(g) => g.name"
                  @add="addGroup" @select="open">
      <template #row="{ item }">
        <span class="flex-1 min-w-0 truncate font-medium text-gray-900 dark:text-white">{{ item.name || 'Unbenannt' }}</span>
        <span v-if="item.required" class="text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 whitespace-nowrap">🔒 Pflicht</span>
        <span v-if="item.hidden" class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-500 whitespace-nowrap">versteckt</span>
        <span class="text-xs text-gray-400 whitespace-nowrap">{{ item.members.length }} 👤</span>
      </template>
    </SettingsList>

    <template v-else-if="groups[selected]">
      <div class="flex items-center justify-between mb-4">
        <button @click="back()" class="btn-secondary">← Zurück</button>
        <button v-if="!groups[selected].required" @click="removeGroup(selected)"
                class="text-sm text-red-500 hover:text-red-600 hover:underline">Löschen</button>
      </div>

      <div class="card-section space-y-5">
        <div class="flex items-center gap-2">
          <div class="flex-1">
            <label class="lbl">Name</label>
            <input v-if="!groups[selected].required" v-model="groups[selected].name" class="set-input w-full font-semibold" />
            <p v-else class="text-lg font-semibold text-gray-900 dark:text-white">{{ groups[selected].name }}</p>
          </div>
          <span v-if="groups[selected].required"
                title="Von den Workflows benötigt – nicht umbenennbar/löschbar. Mitglieder & Verteiler bleiben editierbar."
                class="mt-5 inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/20
                       text-amber-700 dark:text-amber-300 px-2.5 py-1 text-xs font-medium whitespace-nowrap">🔒 Pflichtgruppe</span>
        </div>

        <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none w-fit">
          <input type="checkbox" v-model="groups[selected].hidden"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30 cursor-pointer" />
          <span>Nicht in Auswahl-Dropdowns anzeigen</span>
        </label>

        <div class="grid md:grid-cols-2 gap-6">
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Mitglieder</p>
              <span class="text-xs text-gray-400">{{ groups[selected].members.length }}</span>
            </div>
            <div class="flex flex-wrap gap-2 min-h-[36px]">
              <span v-for="uid in groups[selected].members" :key="uid"
                    class="inline-flex items-center gap-1.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm">
                {{ userName(uid) }}
                <button @click="removeMember(groups[selected], uid)" class="hover:text-red-500 transition">✕</button>
              </span>
            </div>
            <div class="flex gap-2">
              <UserSelect label="" placeholder="Benutzer hinzufügen…"
                          :model-value="memberSel" @update:model-value="memberSel = $event" class="flex-1" />
              <button @click="addMember" class="btn-primary self-end">+</button>
            </div>
          </div>
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Verteiler (E-Mail)</p>
              <span class="text-xs text-gray-400">{{ groups[selected].distributions.length }}</span>
            </div>
            <div class="flex flex-wrap gap-2 min-h-[36px]">
              <span v-for="mail in groups[selected].distributions" :key="mail"
                    class="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 dark:bg-emerald-900/20
                           text-emerald-700 dark:text-emerald-300 px-3 py-1 text-sm">
                {{ mail }}
                <button @click="removeDistribution(groups[selected], mail)" class="hover:text-red-500 transition">✕</button>
              </span>
            </div>
            <div class="flex gap-2">
              <input v-model="distInput" @keydown.enter.prevent="addDistribution"
                     type="email" placeholder="Neue Verteiler-Mail…" class="set-input flex-1" />
              <button @click="addDistribution"
                      class="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm transition">+</button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
