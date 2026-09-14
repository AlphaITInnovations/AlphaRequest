<script setup lang="ts">
/**
 * Empfänger-Auswahl für Erinnerungen/Eskalation. Der Wert ist eine Token-Liste
 * (`responsible` | `owner` | `group:<id>` | `user:<id>`) – gemischt aus Rollen,
 * einzelnen Mitarbeitenden und Fachabteilungen.
 *
 * `watchers` fehlt bewusst: Beobachten heißt mitlesen, nicht eskaliert werden.
 * IDs ohne Person/Gruppe werden als rote Chips geführt statt still verworfen –
 * sonst würde ein Speichern die Empfänger unbemerkt verändern.
 */
import { computed } from 'vue'
import { ESCALATION_ROLES, RECIPIENT_LABEL } from '@/lib/processSchema'

const props = defineProps<{
  modelValue: string[]
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const selected = computed<string[]>(() => props.modelValue ?? [])

const roleTokens = computed(() => selected.value.filter((t) => ESCALATION_ROLES.includes(t)))
const userTokens = computed(() => selected.value.filter((t) => t.startsWith('user:')))
const groupTokens = computed(() => selected.value.filter((t) => t.startsWith('group:')))

const userName = (id: string) => props.users.find((u) => u.id === id)?.displayName ?? null
const groupName = (id: string) => props.groups.find((g) => g.id === id)?.name ?? null

/** Mitarbeitende/Fachabteilungen, die noch NICHT gewählt sind (fürs Hinzufügen). */
const addableUsers = computed(() =>
  props.users.filter((u) => !selected.value.includes(`user:${u.id}`)))
const addableGroups = computed(() =>
  props.groups.filter((g) => !selected.value.includes(`group:${g.id}`)))

function set(list: string[]) { emit('update:modelValue', list) }

function toggleRole(role: string) {
  set(selected.value.includes(role)
    ? selected.value.filter((t) => t !== role)
    : [...selected.value, role])
}
function addToken(token: string) {
  if (token && !selected.value.includes(token)) set([...selected.value, token])
}
function removeToken(token: string) {
  set(selected.value.filter((t) => t !== token))
}
function onAddUser(e: Event) {
  const el = e.target as HTMLSelectElement
  if (el.value) { addToken(`user:${el.value}`); el.value = '' }
}
function onAddGroup(e: Event) {
  const el = e.target as HTMLSelectElement
  if (el.value) { addToken(`group:${el.value}`); el.value = '' }
}
</script>

<template>
  <div class="space-y-2.5">
    <!-- Rollen -->
    <div class="flex flex-wrap gap-2">
      <button v-for="role in ESCALATION_ROLES" :key="role" type="button" :disabled="readonly"
              @click="toggleRole(role)"
              class="rounded-full px-3 py-1 text-xs font-medium border transition select-none"
              :class="roleTokens.includes(role)
                ? 'bg-[#3EAAB8]/15 border-[#3EAAB8]/40 text-[#0F7683] dark:text-[#5FD3DE]'
                : 'border-gray-200 dark:border-white/10 text-gray-500 dark:text-gray-400 hover:border-gray-300'">
        {{ RECIPIENT_LABEL[role] ?? role }}
      </button>
    </div>

    <!-- Chips gewählter Mitarbeitender / Fachabteilungen -->
    <div v-if="userTokens.length || groupTokens.length" class="flex flex-wrap gap-2">
      <span v-for="t in userTokens" :key="t"
            class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs"
            :class="userName(t.slice(5))
              ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
              : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'">
        <span aria-hidden="true">👤</span>
        {{ userName(t.slice(5)) ?? `Unbekannt: ${t.slice(5)}` }}
        <button v-if="!readonly" type="button" @click="removeToken(t)"
                class="hover:opacity-70 transition" aria-label="Empfänger entfernen">✕</button>
      </span>
      <span v-for="t in groupTokens" :key="t"
            class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs"
            :class="groupName(t.slice(6))
              ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300'
              : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'">
        <span aria-hidden="true">🏢</span>
        {{ groupName(t.slice(6)) ?? `Unbekannt: ${t.slice(6)}` }}
        <button v-if="!readonly" type="button" @click="removeToken(t)"
                class="hover:opacity-70 transition" aria-label="Empfänger entfernen">✕</button>
      </span>
    </div>

    <!-- Hinzufügen -->
    <div v-if="!readonly" class="grid sm:grid-cols-2 gap-2">
      <select class="afi w-full text-sm" @change="onAddUser">
        <option value="">+ Mitarbeiter:in …</option>
        <option v-for="u in addableUsers" :key="u.id" :value="u.id">{{ u.displayName }}</option>
      </select>
      <select class="afi w-full text-sm" @change="onAddGroup">
        <option value="">+ Fachabteilung …</option>
        <option v-for="g in addableGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
      </select>
    </div>
  </div>
</template>
