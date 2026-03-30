<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { checkBackendHealth } from '@/api/client'

const router  = useRouter()
const retrying = ref(false)
const failed   = ref(false)

async function retry() {
  retrying.value = true
  failed.value   = false
  const ok = await checkBackendHealth()
  if (ok) {
    router.push('/')
  } else {
    failed.value = true
  }
  retrying.value = false
}
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-[#1A2130] flex items-center justify-center p-6">
    <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                rounded-2xl shadow-sm p-10 max-w-md w-full text-center space-y-6">

      <!-- Icon -->
      <div class="flex justify-center">
        <div class="w-16 h-16 rounded-2xl bg-red-50 dark:bg-red-900/20 flex items-center justify-center">
          <svg class="w-8 h-8 text-red-500" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </div>
      </div>

      <!-- Text -->
      <div class="space-y-2">
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
          Server nicht erreichbar
        </h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Das Backend antwortet gerade nicht. Bitte warte einen Moment und versuche es erneut.
          Wenn das Problem anhält, wende dich an die IT.
        </p>
      </div>

      <!-- Fehler nach Retry -->
      <p v-if="failed" class="text-xs text-red-500">
        Server immer noch nicht erreichbar.
      </p>

      <!-- Retry Button -->
      <button
        @click="retry"
        :disabled="retrying"
        class="w-full px-4 py-2.5 rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
               text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed
               flex items-center justify-center gap-2"
      >
        <svg v-if="retrying"
             class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        {{ retrying ? 'Verbinde…' : 'Erneut versuchen' }}
      </button>

    </div>
  </div>
</template>