<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useTheme } from '@/composables/useTheme'
import { client } from '@/api/client'

const auth   = useAuthStore()
const route  = useRoute()
const router = useRouter()
const { dark, toggleDark } = useTheme()

const sidebarOpen  = ref(true)
const mobileOpen   = ref(false)

function isActive(path: string) {
  if (path === '/dashboard') return route.path === '/dashboard'
  return route.path.startsWith(path)
}

// Prozess-Ticket = /tickets/new und alle /tickets/new/:type AUSSER basis-ticket.
// (Sonst würde /tickets/new/basis-ticket auch hier matchen, weil es mit
//  /tickets/new beginnt – dann leuchten beide Buttons.)
const isBasisTicketActive   = computed(() => route.path === '/tickets/new/basis-ticket')
const isProcessTicketActive = computed(
  () => route.path.startsWith('/tickets/new') && !isBasisTicketActive.value,
)

// „Alle Aufträge" = die Liste selbst und ihre Detailansicht (/tickets/overview/:id).
// NICHT die Arbeitsansicht /tickets/view/:type/:id (kommt vom Dashboard) und
// nicht /tickets/new*.
const isAuftraegeActive = computed(
  () => route.path === '/tickets' || route.path.startsWith('/tickets/overview'),
)

function navigate(path: string) {
  router.push(path)
  mobileOpen.value = false
}

// ── Fehler melden / Feedback ───────────────────────────────────────────────
const showFeedback    = ref(false)
const feedbackText    = ref('')
const feedbackSending = ref(false)
const feedbackSent    = ref(false)

function openFeedback() {
  feedbackText.value = ''
  feedbackSent.value = false
  showFeedback.value = true
  mobileOpen.value = false
}
async function submitFeedback() {
  if (!feedbackText.value.trim()) return
  feedbackSending.value = true
  try {
    await client.post('/feedback', { message: feedbackText.value.trim(), page: route.fullPath })
    feedbackSent.value = true
  } catch {
    alert('Fehlerbericht konnte nicht gesendet werden. Bitte später erneut versuchen.')
  } finally {
    feedbackSending.value = false
  }
}

defineProps<{ title?: string }>()
</script>

<template>
  <div class="flex min-h-screen bg-gray-100 dark:bg-[#1A2130] font-sans transition-colors duration-200">

    <!-- ── Mobile Overlay ── -->
    <Transition enter-active-class="transition-opacity duration-200" leave-active-class="transition-opacity duration-200"
                enter-from-class="opacity-0" leave-to-class="opacity-0">
      <div v-if="mobileOpen" class="fixed inset-0 z-40 bg-black/50 md:hidden" @click="mobileOpen = false" />
    </Transition>

    <!-- ── Sidebar ── -->
    <aside
      :class="[
        sidebarOpen ? 'w-64' : 'w-[72px]',
        mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
      ]"
      class="fixed md:sticky top-0 md:top-3 left-0 md:left-auto z-50 md:z-auto
             h-screen md:h-[calc(100vh-1.5rem)] md:m-3 md:rounded-2xl
             flex flex-col flex-shrink-0
             bg-[#3EAAB8] text-white shadow-lg
             transition-all duration-300 overflow-hidden"
    >
      <!-- Brand -->
      <div class="flex items-center justify-between px-4 py-4 border-b border-white/15 min-h-[64px]">
        <div v-if="sidebarOpen" class="flex items-center gap-2.5 min-w-0 cursor-pointer" @click="navigate('/dashboard')">
          <div class="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0">
            <span class="text-sm font-bold">A</span>
          </div>
          <span class="text-base font-semibold tracking-tight truncate">AlphaRequest</span>
        </div>
        <button @click="sidebarOpen = !sidebarOpen"
                class="p-1.5 rounded-lg hover:bg-white/15 transition flex-shrink-0 hidden md:flex">
          <svg class="w-4 h-4 transition-transform duration-200" :class="sidebarOpen ? '' : 'rotate-180'"
               viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="11 17 6 12 11 7"/>
            <polyline points="18 17 13 12 18 7"/>
          </svg>
        </button>
        <!-- Mobile only: close -->
        <button @click="mobileOpen = false" class="p-1.5 rounded-lg hover:bg-white/15 transition md:hidden">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Ticket-Erstellung -->
      <div class="px-3 pt-4 pb-2 space-y-1.5">
        <button @click="navigate('/tickets/new')"
                class="w-full flex items-center gap-3 rounded-xl transition-all duration-150"
                :class="[
                  sidebarOpen ? 'px-3.5 py-2.5' : 'px-0 py-2.5 justify-center',
                  isProcessTicketActive
                    ? 'bg-white text-[#3EAAB8] font-semibold shadow-sm'
                    : 'bg-white/20 hover:bg-white/30 text-white'
                ]">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" d="M12 4v16m8-8H4"/>
          </svg>
          <span v-if="sidebarOpen" class="text-sm truncate">Neues Prozess-Ticket</span>
        </button>
        <button @click="navigate('/tickets/new/basis-ticket')"
                class="w-full flex items-center gap-3 rounded-xl transition-all duration-150"
                :class="[
                  sidebarOpen ? 'px-3.5 py-2.5' : 'px-0 py-2.5 justify-center',
                  isBasisTicketActive
                    ? 'bg-white text-[#3EAAB8] font-semibold shadow-sm'
                    : 'bg-white/20 hover:bg-white/30 text-white'
                ]">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" d="M12 4v16m8-8H4"/>
          </svg>
          <span v-if="sidebarOpen" class="text-sm truncate">Neues Ticket</span>
        </button>
      </div>

      <!-- Nav -->
      <nav class="flex-1 px-2 py-2 space-y-0.5 text-sm overflow-y-auto">

        <p v-if="sidebarOpen" class="px-3 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/50">
          Navigation
        </p>

        <a @click.prevent="navigate('/dashboard')"
           href="/dashboard"
           class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150 cursor-pointer"
           :class="[
             isActive('/dashboard') ? 'bg-white/20 font-medium' : 'hover:bg-white/10',
             sidebarOpen ? '' : 'justify-center'
           ]">
          <div v-if="isActive('/dashboard')" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>
            <rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Übersicht</span>
        </a>

        <a v-if="auth.canView"
           @click.prevent="navigate('/tickets')"
           href="/tickets"
           class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150 cursor-pointer"
           :class="[
             isAuftraegeActive ? 'bg-white/20 font-medium' : 'hover:bg-white/10',
             sidebarOpen ? '' : 'justify-center'
           ]">
          <div v-if="isAuftraegeActive" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2"/>
            <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Alle Aufträge</span>
        </a>

        <!-- Admin -->
        <template v-if="auth.isAdmin">
          <p v-if="sidebarOpen" class="px-3 pt-5 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/50">
            Administration
          </p>
          <div v-else class="mx-3 my-3 border-t border-white/15" />

          <a @click.prevent="navigate('/settings')"
             href="/settings"
             class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150 cursor-pointer"
             :class="[
               isActive('/settings') ? 'bg-white/20 font-medium' : 'hover:bg-white/10',
               sidebarOpen ? '' : 'justify-center'
             ]">
            <div v-if="isActive('/settings')" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
            <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
            <span v-if="sidebarOpen" class="truncate">Einstellungen</span>
          </a>
        </template>
      </nav>

      <!-- User Section -->
      <div class="border-t border-white/15 p-3 space-y-2">
        <!-- Fehler melden / Feedback -->
        <button @click="openFeedback" title="Fehler melden / Feedback"
                class="w-full flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-white/10 transition text-sm"
                :class="sidebarOpen ? '' : 'justify-center'">
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Fehler melden</span>
        </button>

        <!-- Dark mode toggle -->
        <button @click="toggleDark"
                class="w-full flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-white/10 transition text-sm"
                :class="sidebarOpen ? '' : 'justify-center'">
          <svg v-if="!dark" class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <svg v-else class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/>
            <line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">{{ dark ? 'Light Mode' : 'Dark Mode' }}</span>
        </button>

        <!-- User info + Logout -->
        <div class="flex items-center gap-3 px-3 py-2 rounded-xl bg-white/10"
             :class="sidebarOpen ? '' : 'justify-center'">
          <div class="w-8 h-8 rounded-full bg-white/25 flex items-center justify-center flex-shrink-0 text-xs font-bold">
            {{ auth.user?.displayName?.charAt(0) ?? '?' }}
          </div>
          <div v-if="sidebarOpen" class="min-w-0 flex-1">
            <p class="text-sm font-medium truncate leading-tight">{{ auth.user?.displayName }}</p>
            <p class="text-[11px] text-white/60 truncate leading-tight">{{ auth.user?.mail }}</p>
          </div>
          <button v-if="sidebarOpen" @click="auth.logout()" title="Abmelden"
                  class="p-1.5 rounded-lg hover:bg-white/15 transition flex-shrink-0">
            <svg class="w-4 h-4 opacity-80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <!-- ── Main ── -->
    <div class="flex-1 flex flex-col min-w-0">

      <!-- Topbar -->
      <header class="m-3 mb-0 px-5 py-3 rounded-2xl
                     bg-white dark:bg-[#212B3A]
                     border border-gray-200/80 dark:border-white/[0.09]
                     shadow-sm flex justify-between items-center">
        <div class="flex items-center gap-3">
          <!-- Mobile hamburger -->
          <button @click="mobileOpen = true" class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/10 transition md:hidden">
            <svg class="w-5 h-5 text-gray-600 dark:text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
          </button>
          <img src="/logo.png" alt="Logo" class="h-8 w-auto object-contain" />
          <div class="h-5 w-px bg-gray-200 dark:bg-white/10 hidden sm:block"/>
          <span class="text-sm font-medium text-gray-500 dark:text-gray-400 hidden sm:block">
            <slot name="title">{{ title ?? 'AlphaRequest' }}</slot>
          </span>
        </div>
      </header>

      <!-- Content -->
      <main class="flex-1 m-3">
        <div class="bg-white dark:bg-[#212B3A]
                    border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-8 min-h-full">
          <slot />
        </div>
      </main>
    </div>

    <!-- ── Fehler-melden-Modal ── -->
    <Teleport to="body">
      <div v-if="showFeedback"
           class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm"
           @click.self="showFeedback = false">
        <div class="bg-white dark:bg-[#1C2535] rounded-2xl shadow-xl p-6 w-full max-w-md mx-4 space-y-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Fehler melden / Feedback</h2>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              Beschreibe kurz das Problem oder dein Feedback.
            </p>
          </div>

          <template v-if="!feedbackSent">
            <textarea
              v-model="feedbackText" rows="5" autofocus
              placeholder="Was ist passiert? Was hast du erwartet?"
              class="w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                     bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                     placeholder-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30" />
            <div class="flex justify-end gap-3">
              <button @click="showFeedback = false"
                      class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                             text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5">
                Abbrechen
              </button>
              <button @click="submitFeedback" :disabled="!feedbackText.trim() || feedbackSending"
                      class="px-4 py-2 text-sm rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white font-medium
                             disabled:opacity-50 disabled:cursor-not-allowed transition">
                {{ feedbackSending ? 'Wird gesendet…' : 'Senden' }}
              </button>
            </div>
          </template>

          <template v-else>
            <div class="flex items-center gap-2 text-sm text-green-600 dark:text-green-400 py-2">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
              </svg>
              Danke! Dein Bericht wurde gesendet.
            </div>
            <div class="flex justify-end">
              <button @click="showFeedback = false"
                      class="px-4 py-2 text-sm rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white font-medium transition">
                Schließen
              </button>
            </div>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>