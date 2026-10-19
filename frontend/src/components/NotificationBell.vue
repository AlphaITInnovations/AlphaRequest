<script setup lang="ts">
/**
 * Glocke in der Kopfleiste: Ungelesen-Zahl + aufklappbare Liste der In-App-
 * Benachrichtigungen. Ergänzung zur Mail (die bleibt unverändert sparsam).
 * Klick auf eine Meldung: als gelesen markieren und den Auftrag öffnen.
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '@/stores/notificationStore'
import type { AppNotification } from '@/api/notifications'
import { absoluteTime, relativeTime } from '@/lib/processEventLabels'
import { badgeText, bellLabel, kindMeta } from '@/lib/notificationFormat'

const store = useNotificationStore()
const router = useRouter()
const offen = ref(false)
const root = ref<HTMLElement | null>(null)
const knopf = ref<HTMLButtonElement | null>(null)

const label = computed(() => bellLabel(store.unread))

async function umschalten() {
  offen.value = !offen.value
  if (offen.value) await store.loadList()
}

function schliessen(fokusZurueck = false) {
  offen.value = false
  if (fokusZurueck) void nextTick(() => knopf.value?.focus())
}

async function oeffnen(n: AppNotification) {
  void store.markRead(n)
  schliessen()
  if (!n.link) return
  // Gleiche Seite schon offen? Dann navigiert der Router nicht – die Seite soll
  // trotzdem den neuen Stand zeigen.
  if (router.resolve(n.link).fullPath === router.currentRoute.value.fullPath) store.reloadTick++
  else await router.push(n.link)
}

function onDocumentClick(e: MouseEvent) {
  if (offen.value && root.value && !root.value.contains(e.target as Node)) schliessen()
}

function onKey(e: KeyboardEvent) {
  if (offen.value && e.key === 'Escape') schliessen(true)
}

onMounted(() => {
  store.startPolling()
  document.addEventListener('mousedown', onDocumentClick)
  document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  store.stopPolling()
  document.removeEventListener('mousedown', onDocumentClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="relative">
    <button ref="knopf" type="button" @click="umschalten"
            :aria-label="label" :title="label" :aria-expanded="offen" aria-haspopup="dialog"
            class="relative p-2 rounded-lg text-gray-500 dark:text-gray-300
                   hover:bg-gray-100 dark:hover:bg-white/10 transition">
      <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      <span v-if="store.unread > 0" aria-hidden="true"
            class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full
                   bg-red-500 text-white text-[10px] font-semibold leading-[18px] text-center">
        {{ badgeText(store.unread) }}
      </span>
    </button>

    <div v-if="offen" role="dialog" aria-label="Benachrichtigungen"
         class="absolute right-0 mt-2 z-50 w-[22rem] max-w-[calc(100vw-3rem)]
                rounded-2xl border border-gray-200/80 dark:border-white/10
                bg-white dark:bg-[#1C2535] shadow-xl overflow-hidden">
      <div class="flex items-center justify-between gap-2 px-4 py-3
                  border-b border-gray-100 dark:border-white/10">
        <span class="text-sm font-semibold text-gray-900 dark:text-white">Benachrichtigungen</span>
        <button v-if="store.unread > 0 && store.items.length" type="button" @click="store.markAllRead()"
                :disabled="store.loading"
                class="text-xs text-[#3EAAB8] hover:underline disabled:opacity-40">Alle als gelesen</button>
      </div>

      <div class="max-h-[70vh] overflow-y-auto">
        <p v-if="store.loading && !store.items.length" class="px-4 py-6 text-sm text-gray-400 text-center">
          Wird geladen …
        </p>
        <p v-else-if="store.loadError && !store.items.length" class="px-4 py-6 text-sm text-gray-400 text-center">
          Benachrichtigungen konnten nicht geladen werden.
        </p>
        <p v-else-if="!store.items.length" class="px-4 py-8 text-sm text-gray-400 text-center">
          Keine Benachrichtigungen.
        </p>

        <ul v-else>
          <li v-for="n in store.items" :key="n.id">
            <button type="button" @click="oeffnen(n)"
                    class="w-full text-left flex gap-3 px-4 py-3 transition
                           hover:bg-gray-50 dark:hover:bg-white/[0.04]
                           border-b border-gray-50 dark:border-white/[0.04]"
                    :class="n.read_at ? '' : 'bg-[#3EAAB8]/[0.05]'">
              <span class="mt-1.5 w-2 h-2 rounded-full flex-shrink-0"
                    :class="n.read_at ? 'bg-transparent' : kindMeta(n.kind).dot" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="flex items-baseline gap-1.5">
                  <span class="text-sm truncate"
                        :class="n.read_at ? 'text-gray-600 dark:text-gray-300' : 'font-semibold text-gray-900 dark:text-white'">
                    {{ n.title }}
                  </span>
                  <span v-if="n.ticket_id" class="text-[11px] text-gray-400 flex-shrink-0">#{{ n.ticket_id }}</span>
                </span>
                <span v-if="n.body" class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
                  {{ n.body }}
                </span>
                <span class="block text-[11px] text-gray-400 mt-1">
                  <span class="sr-only">{{ n.read_at ? 'Gelesen' : 'Ungelesen' }} · </span>
                  {{ kindMeta(n.kind).label }} ·
                  <span :title="absoluteTime(n.created_at)">{{ relativeTime(n.created_at) }}</span>
                </span>
              </span>
            </button>
          </li>
        </ul>

        <div v-if="store.hasMore" class="px-4 py-2 text-center">
          <button type="button" @click="store.loadMore()" :disabled="store.loading"
                  class="text-xs text-[#3EAAB8] hover:underline disabled:opacity-50">
            Ältere laden
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
