<script setup lang="ts">
/**
 * Abschnitts-Hülle für schema-getriebene Formulare.
 *
 * Akzentleiste, Icon-Chip, optionales Badge – die Optik stammt aus den früher
 * handgebauten Formularen und wurde bewusst übernommen, damit die generierten
 * Formulare für die Nutzenden nach demselben Programm aussehen. Der Unterschied:
 * Titel, Variante und Badge kommen aus der Prozess-Definition, nicht aus dem
 * Quelltext.
 */
import { computed, ref, useId, watch } from 'vue'
import type { LayoutSection } from '@/types/process'
import { VARIANT_STYLE } from '@/lib/processSchema'

const props = withDefaults(defineProps<{
  section: LayoutSection
  /** Zusammenklappbar machen, auch wenn der Abschnitt offen startet. */
  collapsible?: boolean
}>(), { collapsible: false })

const v = computed(() => VARIANT_STYLE[props.section.variant] ?? VARIANT_STYLE.default)

/** `collapsed` in der Definition heißt: startet zu – und ist damit aufklappbar. */
const canToggle = computed(() => props.collapsible || props.section.collapsed)

const open = ref(!props.section.collapsed)
// Der Editor tauscht Abschnitte im laufenden Betrieb aus (Vorschau); ohne diesen
// Abgleich behielte die Karte den Zustand des vorherigen Abschnitts.
watch(() => props.section, (s) => { open.value = !s.collapsed })

const bodyId = `layout-section-${useId()}`

function toggle() {
  if (canToggle.value) open.value = !open.value
}
</script>

<template>
  <!-- overflow NICHT clippen: sonst werden aufklappende Dropdowns (UserSelect) am
       Sektionsrand abgeschnitten. Die Akzentleiste oben wird stattdessen selbst
       abgerundet, damit die Ecken sauber bleiben. -->
  <section class="relative rounded-2xl border border-gray-200/80 dark:border-white/[0.09]
                  bg-white dark:bg-[#212B3A] shadow-sm">
    <span class="absolute inset-x-0 top-0 h-1 rounded-t-2xl" :class="v.bar" />
    <div class="p-6 space-y-4">
      <!-- Kopfzeile: als Schaltfläche nur, wenn sie auch etwas schaltet -->
      <component
        :is="canToggle ? 'button' : 'div'"
        :type="canToggle ? 'button' : undefined"
        :aria-expanded="canToggle ? String(open) : undefined"
        :aria-controls="canToggle ? bodyId : undefined"
        class="flex w-full items-center gap-3 text-left"
        @click="toggle"
      >
        <span class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl
                     text-base leading-none"
              :class="v.chip">{{ v.icon }}</span>
        <h2 class="text-base font-semibold text-gray-900 dark:text-white">
          {{ section.title || 'Angaben' }}
        </h2>
        <span v-if="section.badge"
              class="ml-auto text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
              :class="v.badge">{{ section.badge }}</span>
        <svg v-if="canToggle" class="h-4 w-4 flex-shrink-0 text-gray-400 transition-transform"
             :class="[open ? 'rotate-180' : '', section.badge ? 'ml-2' : 'ml-auto']"
             viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" clip-rule="evenodd"
                d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z" />
        </svg>
      </component>

      <p v-if="section.description && open"
         class="text-sm text-gray-500 dark:text-gray-400 -mt-1">{{ section.description }}</p>

      <div v-show="open" :id="bodyId" class="space-y-4">
        <slot />
      </div>
    </div>
  </section>
</template>
