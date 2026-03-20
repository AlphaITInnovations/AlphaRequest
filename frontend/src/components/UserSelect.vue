<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { usersApi, type UserEntry } from '@/api/users'

const props = withDefaults(defineProps<{
  label?:        string
  placeholder?:  string
  modelValue?:   { id: string; name: string } | null
}>(), {
  label:       'Benutzer',
  placeholder: 'Mitarbeiter:in auswählen…',
  modelValue:  null,
})

const emit = defineEmits<{
  'update:modelValue': [value: { id: string; name: string } | null]
}>()

const users   = ref<UserEntry[]>([])
const loading = ref(false)
const open    = ref(false)
const search  = ref(props.modelValue?.name ?? '')
const activeIndex = ref(-1)
let debounce: ReturnType<typeof setTimeout> | null = null

const filtered = computed(() => {
  const q = search.value.toLowerCase().trim()
  return q
    ? users.value.filter(u => u.displayName.toLowerCase().includes(q))
    : users.value
})

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await usersApi.list()
    users.value = data.data.users
  } catch (e) {
    console.error('User fetch failed', e)
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
  // Falls Input leer oder kein Match → Reset
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
  if (!open.value || filtered.value.length === 0) return
  activeIndex.value = (activeIndex.value + step + filtered.value.length) % filtered.value.length
}

function confirm() {
  if (activeIndex.value >= 0 && filtered.value[activeIndex.value]) {
    select(filtered.value[activeIndex.value])
  }
}

function select(user: UserEntry) {
  search.value = user.displayName
  emit('update:modelValue', { id: user.id, name: user.displayName })
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
          Lade Benutzer…
        </div>

        <!-- Results -->
        <template v-else>
          <div
            v-for="(u, i) in filtered" :key="u.id"
            @mousedown.prevent="select(u)"
            class="px-4 py-2.5 cursor-pointer text-sm transition-colors"
            :class="[
              i === activeIndex
                ? 'bg-[#3EAAB8]/15 text-[#3EAAB8]'
                : 'text-gray-800 dark:text-gray-200 hover:bg-[#3EAAB8]/10',
              modelValue?.id === u.id ? 'font-medium' : '',
            ]"
          >
            {{ u.displayName }}
          </div>

          <!-- Empty -->
          <div v-if="filtered.length === 0"
               class="px-4 py-3 text-sm text-gray-400 italic">
            Keine Treffer
          </div>
        </template>
      </div>
    </Transition>

  </div>
</template>