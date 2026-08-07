<script setup lang="ts">
/**
 * Modal zum Anlegen eines neuen Prozesses bzw. zum Kopieren eines bestehenden.
 *
 * Der Schlüssel ist unveränderlich, sobald der Prozess existiert – deshalb wird
 * er hier bewusst zur Bestätigung angeboten und nicht still aus dem Namen
 * abgeleitet. Der Vorschlag greift nur so lange, bis er von Hand angefasst wird.
 */
import { computed, nextTick, ref, watch, onUnmounted } from 'vue'
import { createProcess, duplicateProcess } from '@/api/processes'
import { blankDefinition, isValidProcessKey, suggestProcessKey } from '@/lib/processSchema'
import { errorCode, errorMessage } from '@/lib/processErrors'
import { rememberKey } from '@/components/process/processRegistry'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  open: boolean
  mode?: 'create' | 'duplicate'
  sourceKey?: string | null
}>(), { mode: 'create', sourceKey: null })

const emit = defineEmits<{
  close: []
  created: [payload: { key: string; version: number }]
}>()

const { showToast } = useToast()

const KEY_RULE = 'Kleinbuchstaben, Ziffern und Bindestriche; beginnt mit Buchstabe oder Ziffer; max. 64 Zeichen.'

const name       = ref('')
const key        = ref('')
const keyTouched = ref(false)
const keyError   = ref<string | null>(null)
const submitting = ref(false)

const nameInput = ref<HTMLInputElement | null>(null)
const keyInput  = ref<HTMLInputElement | null>(null)

const isDuplicate = computed(() => props.mode === 'duplicate')
const title       = computed(() => (isDuplicate.value ? 'Prozess kopieren' : 'Neuen Prozess anlegen'))
const submitLabel = computed(() => (isDuplicate.value ? 'Kopie erstellen' : 'Anlegen'))

const keyValid = computed(() => isValidProcessKey(key.value))
const nameOk   = computed(() => isDuplicate.value || name.value.trim().length > 0)
const canSubmit = computed(() => !submitting.value && keyValid.value && nameOk.value
  && (!isDuplicate.value || !!props.sourceKey))

// Solange der Schlüssel nicht von Hand geändert wurde, folgt er dem Namen.
watch(name, (v) => {
  if (!keyTouched.value && !isDuplicate.value) key.value = suggestProcessKey(v)
})
watch(key, () => { keyError.value = null })

function onKeyInput() {
  keyTouched.value = true
}

// ── Öffnen/Schließen ─────────────────────────────────────────────────────────

function onWindowKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && !submitting.value) close()
}

function close() {
  if (submitting.value) return
  emit('close')
}

function reset() {
  name.value = ''
  keyError.value = null
  submitting.value = false
  if (isDuplicate.value) {
    // Vorbelegter Kopie-Schlüssel; gilt sofort als „angefasst", damit ihn
    // nichts mehr überschreibt.
    key.value = props.sourceKey ? suggestProcessKey(`${props.sourceKey}-kopie`) : ''
    keyTouched.value = true
  } else {
    key.value = ''
    keyTouched.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) {
    reset()
    window.addEventListener('keydown', onWindowKey)
    nextTick(() => (isDuplicate.value ? keyInput.value : nameInput.value)?.focus())
  } else {
    window.removeEventListener('keydown', onWindowKey)
  }
})

onUnmounted(() => window.removeEventListener('keydown', onWindowKey))

// ── Absenden ─────────────────────────────────────────────────────────────────

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  keyError.value = null
  try {
    const out = isDuplicate.value
      ? await duplicateProcess(props.sourceKey as string, key.value)
      : await createProcess(blankDefinition(key.value, name.value.trim()))
    // Ohne diesen Eintrag wäre der neue Entwurf in der Übersicht unsichtbar.
    rememberKey(out.key)
    emit('created', { key: out.key, version: out.version })
  } catch (e: any) {
    if (errorCode(e) === 'PROCESS_KEY_EXISTS') {
      keyError.value = 'Dieser Schlüssel ist bereits vergeben. Bitte einen anderen wählen.'
    } else {
      showToast(errorMessage(e, isDuplicate.value ? 'Kopieren fehlgeschlagen' : 'Anlegen fehlgeschlagen'), false)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
           @click.self="close()">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">{{ title }}</h3>

          <p v-if="isDuplicate" class="text-sm text-gray-600 dark:text-gray-300">
            Kopiert wird die Definition von
            <span class="font-mono text-gray-800 dark:text-gray-100">{{ sourceKey || '—' }}</span>.
            Name und Inhalt werden übernommen und lassen sich anschließend im Editor anpassen.
          </p>

          <!-- Name: nur beim Anlegen relevant – die Kopie übernimmt den Namen der Quelle -->
          <div v-if="!isDuplicate">
            <label class="lbl">Name</label>
            <input ref="nameInput" v-model="name" class="set-input w-full"
                   placeholder="z. B. Onboarding Mitarbeitende"
                   @keydown.enter.prevent="submit()" />
          </div>

          <div>
            <label class="lbl">Schlüssel</label>
            <input ref="keyInput" v-model="key" @input="onKeyInput"
                   :class="['set-input w-full font-mono',
                            keyError ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : '']"
                   placeholder="onboarding-mitarbeitende" spellcheck="false" autocomplete="off"
                   @keydown.enter.prevent="submit()" />
            <p v-if="keyError" class="text-xs text-red-500 mt-1">{{ keyError }}</p>
            <p v-else-if="key && !keyValid" class="text-xs text-red-500 mt-1">
              Ungültiger Schlüssel. {{ KEY_RULE }}
            </p>
            <p v-else class="text-xs text-gray-400 mt-1">
              {{ KEY_RULE }} Nachträglich nicht mehr änderbar.
            </p>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button @click="close()" :disabled="submitting"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 disabled:opacity-50 transition">
              Abbrechen
            </button>
            <button @click="submit()" :disabled="!canSubmit"
                    class="px-4 py-2 rounded-xl text-sm font-medium
                           bg-[#3EAAB8] hover:bg-[#2B7D89] text-white transition
                           disabled:opacity-50 disabled:cursor-not-allowed">
              {{ submitting ? 'Bitte warten…' : submitLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
