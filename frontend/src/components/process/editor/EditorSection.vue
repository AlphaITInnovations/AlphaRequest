<script setup lang="ts">
/**
 * Zusammenklappbare Einstellungs-Karte für den Prozess-Editor.
 *
 * Titel + Symbol als Kopf-Schaltfläche, optional eine Zähl-Badge (z. B. „3
 * Regeln"). Der Inhalt liegt im Default-Slot; Aktions-Knöpfe (+ …) gehören
 * bewusst IN den Slot (nicht in den Kopf), damit der Kopf eine reine
 * Auf/Zu-Schaltfläche bleibt (kein verschachteltes <button>).
 */
import { ref } from 'vue'

const props = withDefaults(defineProps<{
  title: string
  icon?: string
  /** Kleine Badge rechts im Kopf (Anzahl/Status). Leer/0 → keine Badge. */
  badge?: string | number | null
  defaultOpen?: boolean
}>(), { defaultOpen: true })

const open = ref(props.defaultOpen)
const showBadge = (b: unknown) => b !== null && b !== undefined && b !== '' && b !== 0
</script>

<template>
  <section class="card-section !p-0 overflow-hidden">
    <button type="button" @click="open = !open" :aria-expanded="open"
            class="w-full flex items-center gap-2.5 px-4 py-3 text-left
                   hover:bg-gray-50/60 dark:hover:bg-white/[0.02] transition">
      <span v-if="icon" class="text-base leading-none w-5 text-center shrink-0 opacity-80">{{ icon }}</span>
      <h3 class="section-title mb-0 flex-1 min-w-0 truncate">{{ title }}</h3>
      <span v-if="showBadge(badge)"
            class="shrink-0 text-[11px] font-medium px-2 py-0.5 rounded-full
                   bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-300">
        {{ badge }}
      </span>
      <svg class="w-4 h-4 shrink-0 text-gray-400 transition-transform"
           :class="open ? 'rotate-180' : ''" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" clip-rule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z" />
      </svg>
    </button>
    <div v-show="open" class="px-4 pb-4">
      <slot />
    </div>
  </section>
</template>
