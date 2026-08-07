<script setup lang="ts">
/** Fehler-/Warnungsliste des Editors. Klick springt zur betroffenen Stelle. */
import { computed } from 'vue'
import type { ProcessIssue } from '@/types/process'

const props = defineProps<{ issues: ProcessIssue[] }>()

const errors = computed(() => props.issues.filter((i) => i.severity === 'error'))
const warnings = computed(() => props.issues.filter((i) => i.severity === 'warning'))

function jump(issue: ProcessIssue) {
  const el = document.getElementById(issue.anchor)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-[#3EAAB8]')
    setTimeout(() => el.classList.remove('ring-2', 'ring-[#3EAAB8]'), 1500)
  }
}
</script>

<template>
  <div v-if="issues.length" class="space-y-2">
    <div v-if="errors.length"
         class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20 p-3">
      <div class="text-sm font-medium text-red-800 dark:text-red-200 mb-1">
        {{ errors.length }} Fehler – Speichern nicht möglich
      </div>
      <ul class="space-y-0.5">
        <li v-for="(i, n) in errors" :key="n">
          <button @click="jump(i)" class="text-left text-xs text-red-700 dark:text-red-300 hover:underline">
            <span class="font-mono opacity-70">{{ i.path }}</span> — {{ i.message }}
            <span v-if="i.source === 'server'" class="opacity-60">(Server)</span>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="warnings.length"
         class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-900/20 p-3">
      <div class="text-sm font-medium text-amber-800 dark:text-amber-200 mb-1">
        {{ warnings.length }} Hinweis(e)
      </div>
      <ul class="space-y-0.5">
        <li v-for="(i, n) in warnings" :key="n">
          <button @click="jump(i)" class="text-left text-xs text-amber-700 dark:text-amber-300 hover:underline">
            <span class="font-mono opacity-70">{{ i.path }}</span> — {{ i.message }}
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
