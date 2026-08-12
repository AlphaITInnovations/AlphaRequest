<script setup lang="ts">
/**
 * Wer darf Aufträge dieses Prozesses anlegen?
 *
 * Bewusst Teil der Definition (nicht mehr in einer separaten Rechte-Verwaltung):
 * So steht alles zu einem Prozess an einer Stelle und wandert bei Export,
 * Import und Kopie mit. Default ist restriktiv – nur Admins.
 */
import { computed } from 'vue'
import type { CreatePermissions } from '@/types/process'

const props = defineProps<{
  modelValue: CreatePermissions
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
}>()

const emit = defineEmits<{ 'update:modelValue': [value: CreatePermissions] }>()

function patch(part: Partial<CreatePermissions>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}

const groupIds = computed(() => new Set(props.modelValue.groups ?? []))
const userIds = computed(() => new Set(props.modelValue.users ?? []))

function toggleGroup(id: string, on: boolean) {
  const next = new Set(groupIds.value)
  on ? next.add(id) : next.delete(id)
  patch({ groups: [...next] })
}

function toggleUser(id: string, on: boolean) {
  const next = new Set(userIds.value)
  on ? next.add(id) : next.delete(id)
  patch({ users: [...next] })
}

/** IDs, die es (nicht mehr) gibt – sichtbar machen statt still schlucken. */
const unknownGroups = computed(() =>
  (props.modelValue.groups ?? []).filter((g) => !props.groups.some((x) => x.id === g)))
const unknownUsers = computed(() =>
  (props.modelValue.users ?? []).filter((u) => !props.users.some((x) => x.id === u)))

const summary = computed(() => {
  if (props.modelValue.everyone) return 'Alle angemeldeten Personen'
  const parts: string[] = []
  const gs = (props.modelValue.groups ?? []).length
  const us = (props.modelValue.users ?? []).length
  if (gs) parts.push(`${gs} Gruppe${gs === 1 ? '' : 'n'}`)
  if (us) parts.push(`${us} Person${us === 1 ? '' : 'en'}`)
  return parts.length ? parts.join(' + ') : 'Nur Administratoren'
})
</script>

<template>
  <section class="card-section" id="pe-createperms">
    <h3 class="section-title">Wer darf diesen Auftrag anlegen?</h3>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
      Gehört zum Prozess und wird beim Export, Import und Kopieren mitgenommen.
      Administratoren dürfen immer. Aktuell: <b>{{ summary }}</b>
    </p>

    <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200 mb-3">
      <input type="checkbox" :checked="modelValue.everyone"
             class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
             @change="patch({ everyone: ($event.target as HTMLInputElement).checked })" />
      <span>
        Alle angemeldeten Personen
        <span class="block text-[11px] text-gray-400">
          Überschreibt die Auswahl unten.
        </span>
      </span>
    </label>

    <div :class="modelValue.everyone ? 'opacity-40 pointer-events-none' : ''"
         class="grid md:grid-cols-2 gap-4">
      <!-- Gruppen -->
      <div>
        <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Fachabteilungen / Gruppen</div>
        <p v-if="!groups.length" class="text-xs text-gray-400 italic">Keine Gruppen vorhanden.</p>
        <div class="max-h-56 overflow-y-auto pr-1 space-y-1">
          <label v-for="g in groups" :key="g.id"
                 class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input type="checkbox" :checked="groupIds.has(g.id)"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                   @change="toggleGroup(g.id, ($event.target as HTMLInputElement).checked)" />
            <span class="truncate">{{ g.name }}</span>
          </label>
        </div>
        <div v-if="unknownGroups.length" class="mt-2 flex flex-wrap gap-1">
          <span v-for="g in unknownGroups" :key="g"
                class="text-[11px] px-1.5 py-0.5 rounded bg-red-100 text-red-700
                       dark:bg-red-900/30 dark:text-red-300">
            Unbekannt: {{ g }}
            <button class="ml-1 hover:underline" @click="toggleGroup(g, false)">entfernen</button>
          </span>
        </div>
      </div>

      <!-- Einzelpersonen -->
      <div>
        <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
          Einzelne Personen <span class="text-gray-400">(Ausnahmen)</span>
        </div>
        <select class="afi w-full" :value="''"
                @change="toggleUser(($event.target as HTMLSelectElement).value, true);
                         ($event.target as HTMLSelectElement).value = ''">
          <option value="">+ Person hinzufügen…</option>
          <option v-for="u in users.filter(x => !userIds.has(x.id))" :key="u.id" :value="u.id">
            {{ u.displayName }}
          </option>
        </select>
        <div class="mt-2 flex flex-wrap gap-1">
          <span v-for="id in modelValue.users" :key="id"
                class="text-[11px] px-1.5 py-0.5 rounded inline-flex items-center gap-1"
                :class="unknownUsers.includes(id)
                  ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                  : 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300'">
            {{ users.find(u => u.id === id)?.displayName || `Unbekannt: ${id}` }}
            <button class="hover:underline" @click="toggleUser(id, false)">✕</button>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
