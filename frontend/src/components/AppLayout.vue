<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useTheme } from '@/composables/useTheme'

const auth  = useAuthStore()
const route = useRoute()
const { dark, toggleDark } = useTheme()

const sidebarOpen = ref(true)

function isActive(path: string) {
  // Exakter Match oder direktes Kind (z.B. /tickets/123) aber nicht /tickets/new/...
  return route.path === path
}

defineProps<{ title?: string }>()
</script>

<template>
  <div class="flex min-h-screen bg-gray-100 dark:bg-[#1A2130] font-sans transition-colors duration-200">

    <!-- ── Sidebar ── -->
    <aside
      :class="sidebarOpen ? 'w-64' : 'w-[72px]'"
      class="hidden md:flex flex-col flex-shrink-0 m-3 rounded-2xl
             bg-[#3EAAB8] text-white shadow-lg transition-all duration-300 overflow-hidden"
    >
      <!-- Brand -->
      <div class="flex items-center justify-between px-4 py-4 border-b border-white/15 min-h-[64px]">
        <span v-if="sidebarOpen" class="text-base font-semibold tracking-tight truncate">
          AlphaRequest
        </span>
        <button
          @click="sidebarOpen = !sidebarOpen"
          class="p-1.5 rounded-lg hover:bg-white/15 transition flex-shrink-0"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <line x1="9" y1="3" x2="9" y2="21"/>
          </svg>
        </button>
      </div>

      <!-- Nav -->
      <nav class="flex-1 px-2 py-4 space-y-0.5 text-sm">

        <a
          href="/dashboard"
          class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150"
          :class="isActive('/dashboard') ? 'bg-white/20 font-medium' : 'hover:bg-white/10'"
        >
          <div v-if="isActive('/dashboard')" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>
            <rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Übersicht</span>
        </a>

        <a
          v-if="auth.isAdmin"
          href="/tickets"
          class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150"
          :class="isActive('/tickets') ? 'bg-white/20 font-medium' : 'hover:bg-white/10'"
        >
          <div v-if="isActive('/tickets')" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Auftragsübersicht</span>
        </a>

        <a
          v-if="auth.isAdmin"
          href="/settings"
          class="relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150"
          :class="isActive('/settings') ? 'bg-white/20 font-medium' : 'hover:bg-white/10'"
        >
          <div v-if="isActive('/settings')" class="absolute left-0 top-2 bottom-2 w-0.5 bg-white rounded-r-full"/>
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <span v-if="sidebarOpen" class="truncate">Admin · Settings</span>
        </a>

      </nav>

      <!-- Footer -->
      <div class="px-2 py-3 border-t border-white/15">
        <button
          @click="auth.logout()"
          class="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-white/10 transition w-full text-sm"
        >
          <svg class="w-4 h-4 flex-shrink-0 opacity-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          <span v-if="sidebarOpen">Logout</span>
        </button>
      </div>
    </aside>

    <!-- ── Main ── -->
    <div class="flex-1 flex flex-col min-w-0">

      <!-- Topbar -->
      <header class="m-3 mb-0 px-6 py-3.5 rounded-2xl
                     bg-white dark:bg-[#212B3A]
                     border border-gray-200/80 dark:border-white/[0.09]
                     shadow-sm flex justify-between items-center">
        <div class="flex items-center gap-3">
          <img src="/logo.png" alt="Logo" class="h-8 w-auto object-contain" />
          <div class="h-5 w-px bg-gray-200 dark:bg-white/10"/>
          <span class="text-sm font-medium text-gray-500 dark:text-gray-400">
            <slot name="title">AlphaRequest</slot>
          </span>
        </div>

        <div class="flex items-center gap-2">
          <button
            @click="toggleDark"
            class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-white/5 transition"
            :title="dark ? 'Light Mode' : 'Dark Mode'"
          >
            <!-- Moon -->
            <svg v-if="!dark" class="w-5 h-5 text-[#3EAAB8]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
            <!-- Sun -->
            <svg v-else class="w-5 h-5 text-[#3EAAB8]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/>
              <line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/>
              <line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
          </button>

          <button
            @click="auth.logout()"
            class="px-4 py-2 rounded-xl bg-[#3EAAB8] hover:bg-[#2B7D89] text-white
                   text-sm font-medium transition-colors duration-150"
          >
            Abmelden
          </button>
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
  </div>
</template>