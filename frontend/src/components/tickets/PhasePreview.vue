<script setup lang="ts">
// Zeigt beim Erstellen, welche Phasen der Auftrag durchlaufen wird.
// Schritt 1 (Erstellung) ist „jetzt" und hervorgehoben, der Rest ist Ausblick.
defineProps<{ phases: { key: string; label: string; type: string }[] }>()
</script>

<template>
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm p-4 sm:p-5">
    <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
      So läuft dieser Auftrag
    </p>
    <ol class="flex flex-wrap items-center gap-y-3">
      <li v-for="(p, i) in phases" :key="p.key" class="flex items-center">
        <div class="flex items-center gap-2">
          <span class="w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center flex-shrink-0"
                :class="i === 0 ? 'bg-[#3EAAB8] text-white' : 'bg-[#3EAAB8]/10 text-[#3EAAB8]'">
            {{ i + 1 }}
          </span>
          <span class="text-sm font-medium whitespace-nowrap"
                :class="i === 0 ? 'text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-300'">
            {{ p.label }}
          </span>
        </div>
        <svg v-if="i < phases.length - 1"
             class="w-4 h-4 mx-2 sm:mx-3 text-gray-300 dark:text-gray-600 flex-shrink-0"
             viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
        </svg>
      </li>
    </ol>
  </div>
</template>
