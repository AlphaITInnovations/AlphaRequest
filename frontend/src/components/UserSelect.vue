<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { usersApi, type UserEntry } from '@/api/users'
import { client } from '@/api/client'

interface GroupEntry { id: string; name: string }

const props = withDefaults(defineProps<{
  label?:        string
  placeholder?:  string
  modelValue?:   { id: string; name: string } | null
  showGroups?:   boolean
}>(), {
  label:       'Benutzer',
  placeholder: 'Mitarbeiter:in auswählen…',
  modelValue:  null,
  showGroups:  false,
})

const emit = defineEmits<{
  'update:modelValue': [value: { id: string; name: string } | null]
}>()

const users   = ref<UserEntry[]>([])
const groups  = ref<GroupEntry[]>([])
const loading = ref(false)
const open    = ref(false)
const search  = ref(props.modelValue?.name ?? '')
const activeIndex = ref(-1)
let debounce: ReturnType<typeof setTimeout> | null = null

// Filtered groups (only when showGroups is true)
const filteredGroups = computed(() => {
  if (!props.showGroups) return []
  const q = search.value.toLowerCase().trim()
  return q
    ? groups.value.filter(g => g.name.toLowerCase().includes(q))
    : groups.value
})

// Filtered users
const filteredUsers = computed(() => {
  const q = search.value.toLowerCase().trim()
  return q
    ? users.value.filter(u => u.displayName.toLowerCase().includes(q))
    : users.value
})

// Combined count for keyboard navigation
const totalFiltered = computed(() => filteredGroups.value.length + filteredUsers.value.length)

onMounted(async () => {
  loading.value = true
  try {
    const [usersRes, groupsRes] = await Promise.all([
      usersApi.list(),
      props.showGroups
        ? client.get<{ data: GroupEntry[] }>('/groups')
        : Promise.resolve(null),
    ])
    users.value = usersRes.data.data.users
    if (groupsRes) {
      groups.value = groupsRes.data.data
    }
  } catch (e) {
    console.error('User/Group fetch failed', e)
  } finally {
    loading.value = false
  }
})

function openDropdown() {
  open.value = true
  activeIndex.value = -1
}

function close() {
  open.value = false
  activeIndex.value = -1
  if (!props.modelValue || search.value !== props.modelValue.name) {
    search.value = props.modelValue?.name ?? ''
  }
}

function onInput() {
  open.value = true
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => { activeIndex.value = -1 }, 150)
}

function move(step: number) {
  if (!open.value || totalFiltered.value === 0) return
  activeIndex.value = (activeIndex.value + step + totalFiltered.value) % totalFiltered.value
}

function confirm() {
  if (activeIndex.value < 0) return
  const groupCount = filteredGroups.value.length
  if (activeIndex.value < groupCount) {
    selectGroup(filteredGroups.value[activeIndex.value])
  } else {
    selectUser(filteredUsers.value[activeIndex.value - groupCount])
  }
}

function selectUser(user: UserEntry) {
  search.value = user.displayName
  emit('update:modelValue', { id: user.id, name: user.displayName })
  open.value = false
  activeIndex.value = -1
}

function selectGroup(group: GroupEntry) {
  search.value = group.name
  emit('update:modelValue', { id: group.id, name: group.name })
  open.value = false
  activeIndex.value = -1
}

// Click outside
const root = ref<HTMLElement | null>(null)
function onClickOutside(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) close()
}
onMounted(() => document.addEventListener('mousedown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))
</script>

<template>
  <div ref="root" class="relative">

    <!-- Label -->
    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
      {{ label }}
    </label>

    <!-- Input -->
    <input
      type="text"
      v-model="search"
      @focus="openDropdown"
      @input="onInput"
      @keydown.arrow-down.prevent="move(1)"
      @keydown.arrow-up.prevent="move(-1)"
      @keydown.enter.prevent="confirm"
      @keydown.escape="close"
      :placeholder="placeholder"
      autocomplete="off"
      class="w-full rounded-xl border border-gray-200 dark:border-white/10
             bg-white dark:bg-[#263040]
             text-gray-900 dark:text-gray-100
             placeholder-gray-400 dark:placeholder-gray-500
             px-3.5 py-2.5 text-sm
             focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50
             transition"
    />

    <!-- Dropdown -->
    <Transition
      enter-active-class="transition ease-out duration-100"
      enter-from-class="opacity-0 translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition ease-in duration-75"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-show="open"
        class="absolute z-50 w-full mt-1.5 rounded-xl
               bg-white dark:bg-[#212B3A]
               border border-gray-200 dark:border-white/[0.09]
               shadow-lg overflow-hidden max-h-60 overflow-y-auto"
      >
        <!-- Loading -->
        <div v-if="loading" class="px-4 py-3 text-sm text-gray-400 italic">
          Lade…
        </div>

        <template v-else>

          <!-- ── Fachabteilungen ── -->
          <template v-if="filteredGroups.length > 0">
            <div class="px-3.5 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider bg-gray-50 dark:bg-[#1A2130] sticky top-0">
              Fachabteilungen
            </div>
            <div
              v-for="(g, i) in filteredGroups" :key="`g-${g.id}`"
              @mousedown.prevent="selectGroup(g)"
              class="px-4 py-2.5 cursor-pointer text-sm transition-colors flex items-center gap-2.5"
              :class="[
                i === activeIndex
                  ? 'bg-[#3EAAB8]/15 text-[#3EAAB8]'
                  : 'text-gray-800 dark:text-gray-200 hover:bg-[#3EAAB8]/10',
                modelValue?.id === g.id ? 'font-medium' : '',
              ]"
            >
              <span class="w-5 h-5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400
                           flex items-center justify-center text-xs flex-shrink-0">
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </span>
              {{ g.name }}
            </div>
          </template>

          <!-- ── Benutzer ── -->
          <template v-if="filteredUsers.length > 0">
            <div v-if="showGroups"
                 class="px-3.5 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider bg-gray-50 dark:bg-[#1A2130] sticky top-0">
              Benutzer
            </div>
            <div
              v-for="(u, i) in filteredUsers" :key="u.id"
              @mousedown.prevent="selectUser(u)"
              class="px-4 py-2.5 cursor-pointer text-sm transition-colors"
              :class="[
                (i + filteredGroups.length) === activeIndex
                  ? 'bg-[#3EAAB8]/15 text-[#3EAAB8]'
                  : 'text-gray-800 dark:text-gray-200 hover:bg-[#3EAAB8]/10',
                modelValue?.id === u.id ? 'font-medium' : '',
              ]"
            >
              {{ u.displayName }}
            </div>
          </template>

          <!-- Empty -->
          <div v-if="filteredGroups.length === 0 && filteredUsers.length === 0"
               class="px-4 py-3 text-sm text-gray-400 italic">
            Keine Treffer
          </div>
        </template>
      </div>
    </Transition>

  </div>
</template>