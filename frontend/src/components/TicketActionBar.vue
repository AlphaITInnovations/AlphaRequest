<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  phase: 'create' | 'edit' | 'view'
  loading?: boolean
  confirmCreateOpen?:   boolean
  confirmCompleteOpen?: boolean
  departmentName?:   string
  departmentStatus?: string
  canComplete?:      boolean
  isAdmin?:          boolean
}>()

const emit = defineEmits<{
  'create':             []
  'create-confirmed':   []
  'create-cancelled':   []
  'save':               []
  'complete':           []
  'complete-confirmed': []
  'complete-cancelled': []
  'archive':            []
  'department-done':    []
  'department-edit':    []
}>()

const confirmDeptDone = ref(false)

const DEPT_STATUS_LABEL: Record<string, string> = {
  done:     '✔ Ausgeführt',
  rejected: '✖ Abgelehnt',
}
const DEPT_STATUS_CLASS: Record<string, string> = {
  done:     'text-green-600',
  rejected: 'text-red-600',
}
</script>

<template>
  <!-- Spacer damit Content nicht hinter der Bar verschwindet -->
  <div class="h-20" />

  <!-- ── Sticky Action Bar ── -->
  <div class="sticky bottom-4 z-40 mt-4">
    <div class="border border-gray-200 dark:border-white/[0.09]
                bg-white/95 dark:bg-[#212B3A]/95
                backdrop-blur rounded-2xl shadow-lg">
        <div class="py-3 px-4 flex items-center justify-between gap-4">

          <!-- Left: Department Status (view phase) -->
          <div class="min-w-0">
            <template v-if="phase === 'view' && departmentName">
              <div class="text-base font-semibold text-gray-900 dark:text-white truncate">
                Fachabteilung:
                <span class="text-[#3EAAB8]">{{ departmentName }}</span>
              </div>
              <div class="text-sm mt-0.5">
                Status:
                <span
                  :class="DEPT_STATUS_CLASS[departmentStatus ?? ''] ?? 'text-[#3EAAB8] font-semibold'"
                  class="font-semibold"
                >
                  {{ DEPT_STATUS_LABEL[departmentStatus ?? ''] ?? '🛠 In Bearbeitung' }}
                </span>
              </div>
            </template>
          </div>

          <!-- Right: Buttons -->
          <div class="flex items-center gap-3 flex-shrink-0">

            <!-- Abbrechen -->
            <a href="/dashboard"
               class="px-5 py-2 rounded-xl text-sm font-medium
                      bg-gray-100 dark:bg-white/10
                      text-gray-700 dark:text-gray-200
                      hover:bg-gray-200 dark:hover:bg-white/15
                      transition">
              Abbrechen
            </a>

            <!-- CREATE -->
            <template v-if="phase === 'create'">
              <button
                @click="emit('create')"
                :disabled="loading"
                class="px-6 py-2 rounded-xl text-sm font-medium
                       bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                       disabled:opacity-60 disabled:cursor-not-allowed transition"
              >
                Auftrag erstellen
              </button>
            </template>

            <!-- EDIT -->
            <template v-else-if="phase === 'edit'">
              <button
                @click="emit('save')"
                :disabled="loading"
                class="px-6 py-2 rounded-xl text-sm font-medium
                       bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                       disabled:opacity-60 transition"
              >
                Speichern
              </button>
              <button
                @click="emit('complete')"
                :disabled="loading"
                class="px-6 py-2 rounded-xl text-sm font-medium
                       bg-green-600 hover:bg-green-700 text-white
                       disabled:opacity-60 transition"
              >
                Abschließen
              </button>
            </template>

            <!-- VIEW -->
            <template v-else-if="phase === 'view'">
              <template v-if="canComplete && departmentStatus !== 'done'">
                <button
                  @click="emit('department-edit')"
                  class="px-4 py-2 rounded-xl text-sm font-medium
                         border border-yellow-400 text-yellow-700 dark:text-yellow-400
                         bg-yellow-50 dark:bg-yellow-900/20
                         hover:bg-yellow-100 dark:hover:bg-yellow-900/30 transition"
                >
                  Bearbeiten
                </button>
                <button
                  @click="confirmDeptDone = true"
                  class="px-6 py-2 rounded-xl text-sm font-medium
                         bg-emerald-600 hover:bg-emerald-700 text-white transition"
                >
                  ✔ Ausgeführt
                </button>
              </template>
              <template v-if="isAdmin && !departmentName">
                <button
                  @click="emit('archive')"
                  class="px-6 py-2 rounded-xl text-sm font-medium
                         bg-gray-500 hover:bg-gray-600 text-white transition"
                >
                  Archivieren
                </button>
              </template>
            </template>

          </div>
        </div>
      </div>
  </div>

  <!-- ── Modal: Erstellen bestätigen ── -->
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="confirmCreateOpen"
           class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">
            Auftrag erstellen
          </h3>
          <p class="text-sm text-gray-600 dark:text-gray-300">
            Wollen Sie den Auftrag jetzt erstellen und der verantwortlichen Person zuweisen?
          </p>
          <div class="flex justify-end gap-3 pt-2">
            <button @click="emit('create-cancelled')"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 transition">
              Abbrechen
            </button>
            <button @click="emit('create-confirmed')"
                    class="px-4 py-2 rounded-xl text-sm font-medium
                           bg-[#3EAAB8] hover:bg-[#2B7D89] text-white transition">
              Erstellen
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- ── Modal: Abschließen bestätigen ── -->
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="confirmCompleteOpen"
           class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">
            Auftrag abschließen
          </h3>
          <p class="text-sm text-gray-600 dark:text-gray-300">
            Wollen Sie den Auftrag wirklich abschließen?
            <br><br>
            Eine Bearbeitung ist danach nicht mehr möglich.
          </p>
          <div class="flex justify-end gap-3 pt-2">
            <button @click="emit('complete-cancelled')"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 transition">
              Abbrechen
            </button>
            <button @click="emit('complete-confirmed')"
                    class="px-4 py-2 rounded-xl text-sm font-medium
                           bg-red-600 hover:bg-red-700 text-white transition">
              Abschließen
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- ── Modal: Department done ── -->
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="confirmDeptDone"
           class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">
            Auftrag als ausgeführt markieren
          </h3>
          <p class="text-sm text-gray-600 dark:text-gray-300">
            Wurde der Auftrag wirklich ausgeführt?
            <br><br>
            Danach kann die Fachabteilung den Auftrag nicht mehr bearbeiten.
          </p>
          <div class="flex justify-end gap-3 pt-2">
            <button @click="confirmDeptDone = false"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 transition">
              Abbrechen
            </button>
            <button @click="confirmDeptDone = false; emit('department-done')"
                    class="px-4 py-2 rounded-xl text-sm font-medium
                           bg-emerald-600 hover:bg-emerald-700 text-white transition">
              Ausführung bestätigen
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>