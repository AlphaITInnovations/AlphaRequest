<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'
import { usersApi, type UserEntry } from '@/api/users'
import UserSelect from '@/components/UserSelect.vue'
import { useToast } from '@/composables/useToast'
import { useSaver } from '@/composables/settingsSave'

const { showToast } = useToast()

interface Group { id: string; name: string; members: string[]; distributions: string[]; required?: boolean; hidden?: boolean }

const groups      = ref<Group[]>([])
const snapshot    = ref<Record<string, string>>({})   // id -> serialisierter Feldstand (zuletzt gespeichert)
const users       = ref<UserEntry[]>([])
const loading     = ref(true)
const newGroupName = ref('')
const distInput    = ref<Record<string, string>>({})
const groupMember  = ref<Record<string, { id: string; name: string } | null>>({})

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function serialize(g: Group): string {
  return JSON.stringify({ name: g.name, members: [...g.members].sort(),
                          distributions: [...g.distributions].sort(), hidden: !!g.hidden })
}
function userName(id: string) { return users.value.find(u => u.id === id)?.displayName ?? id }

async function loadGroups() {
  loading.value = true
  try {
    const [grp, usr] = await Promise.all([client.get('/settings/groups'), usersApi.list()])
    groups.value = grp.data.data
    users.value  = usr.data.data.users
    const snap: Record<string, string> = {}
    groups.value.forEach(g => {
      snap[g.id] = serialize(g)
      distInput.value[g.id]   = ''
      groupMember.value[g.id] = null
    })
    snapshot.value = snap
  } finally {
    loading.value = false
  }
}

// ── Sofort-Aktionen (Anlegen / Löschen) ─────────────────────────────────────
async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  try {
    const { data } = await client.post('/settings/groups', { name, distributions: [] })
    const g: Group = data.data
    groups.value.push(g)
    snapshot.value[g.id] = serialize(g)
    distInput.value[g.id] = ''
    groupMember.value[g.id] = null
    newGroupName.value = ''
    showToast('Gruppe erstellt', true)
  } catch { showToast('Fehler beim Erstellen', false) }
}
async function deleteGroup(g: Group) {
  if (g.required) return
  if (!confirm(`Fachabteilung "${g.name}" wirklich löschen?`)) return
  try {
    await client.delete(`/settings/groups/${g.id}`)
    groups.value = groups.value.filter(x => x.id !== g.id)
    delete snapshot.value[g.id]
    showToast('Gelöscht', true)
  } catch { showToast('Löschen nicht möglich', false) }
}

// ── Lokale Feld-Änderungen (Speichern via Sticky-Bar) ────────────────────────
function addMember(g: Group) {
  const m = groupMember.value[g.id]
  if (!m) return
  if (!g.members.includes(m.id)) g.members.push(m.id)
  groupMember.value[g.id] = null
}
function removeMember(g: Group, uid: string) { g.members = g.members.filter(m => m !== uid) }
function addDistribution(g: Group) {
  const mail = (distInput.value[g.id] || '').trim().toLowerCase()
  if (!mail) return
  if (!EMAIL_RE.test(mail)) { showToast('Ungültige E-Mail', false); return }
  if (g.distributions.includes(mail)) { showToast('Existiert bereits', false); return }
  g.distributions.push(mail)
  distInput.value[g.id] = ''
}
function removeDistribution(g: Group, mail: string) { g.distributions = g.distributions.filter(m => m !== mail) }

async function saveGroups() {
  const changed = groups.value.filter(g => serialize(g) !== snapshot.value[g.id])
  if (changed.length === 0) return
  setSaving(true)
  try {
    for (const g of changed) {
      const { data } = await client.put(`/settings/groups/${g.id}`, {
        name: g.name, members: g.members, distributions: g.distributions, hidden: g.hidden ?? false,
      })
      Object.assign(g, data.data)
      snapshot.value[g.id] = serialize(g)
    }
    showToast('Gespeichert', true)
  } catch (e: any) {
    showToast(e?.response?.data?.detail || 'Fehler beim Speichern', false)
  } finally {
    setSaving(false)
  }
}

const dirty = computed(() => groups.value.some(g => serialize(g) !== snapshot.value[g.id]))
const { setSaving } = useSaver({ dirty, save: saveGroups, reset: () => loadGroups() })

onMounted(loadGroups)
</script>

<template>
  <section>
    <h2 class="section-title">Fachabteilungen</h2>
    <div class="card-section mb-4 flex gap-3">
      <input v-model="newGroupName" @keydown.enter.prevent="createGroup" placeholder="Neue Gruppe…" class="set-input flex-1" />
      <button @click="createGroup" class="btn-primary">Erstellen</button>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>

    <div v-else class="space-y-4">
      <div v-for="g in groups" :key="g.id" class="card-section space-y-5">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 flex-1 min-w-0">
            <input v-if="!g.required" v-model="g.name" class="set-input flex-1 min-w-0 font-semibold" />
            <h3 v-else class="text-lg font-semibold text-gray-900 dark:text-white">{{ g.name }}</h3>
            <span v-if="g.required"
                  title="Diese Fachabteilung wird von den Workflows benötigt und kann nicht umbenannt oder gelöscht werden. Mitglieder und Verteiler lassen sich weiterhin bearbeiten."
                  class="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/20
                         text-amber-700 dark:text-amber-300 px-2.5 py-1 text-xs font-medium whitespace-nowrap">
              🔒 Pflichtgruppe
            </span>
          </div>
          <button v-if="!g.required" @click="deleteGroup(g)"
                  class="p-2 rounded-xl hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500 transition flex-shrink-0">🗑</button>
        </div>

        <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none w-fit">
          <input type="checkbox" v-model="g.hidden"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30 cursor-pointer" />
          <span>Nicht in Auswahl-Dropdowns anzeigen</span>
          <span class="text-xs text-gray-400 hidden sm:inline">– für Gruppen, die nur über spezielle Phasen automatisch zugewiesen werden</span>
        </label>

        <div class="grid md:grid-cols-2 gap-6">
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Mitglieder</p>
              <span class="text-xs text-gray-400">{{ g.members.length }}</span>
            </div>
            <div class="flex flex-wrap gap-2 min-h-[36px]">
              <span v-for="uid in g.members" :key="uid"
                    class="inline-flex items-center gap-1.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm">
                {{ userName(uid) }}
                <button @click="removeMember(g, uid)" class="hover:text-red-500 transition">✕</button>
              </span>
            </div>
            <div class="flex gap-2">
              <UserSelect label="" placeholder="Benutzer hinzufügen…"
                          :model-value="groupMember[g.id]"
                          @update:model-value="groupMember[g.id] = $event" class="flex-1" />
              <button @click="addMember(g)" class="btn-primary self-end">+</button>
            </div>
          </div>
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">Verteiler (E-Mail)</p>
              <span class="text-xs text-gray-400">{{ g.distributions.length }}</span>
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
                     type="email" placeholder="Neue Verteiler-Mail…" class="set-input flex-1" />
              <button @click="addDistribution(g)"
                      class="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm transition">+</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
