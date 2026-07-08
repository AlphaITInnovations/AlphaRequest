<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteUpdate } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { useSettingsSaveBar } from '@/composables/settingsSave'
import EnvInfoPanel from '@/components/settings/EnvInfoPanel.vue'
import CompaniesPanel from '@/components/settings/CompaniesPanel.vue'
import DepartmentsPanel from '@/components/settings/DepartmentsPanel.vue'
import TicketPermissionsPanel from '@/components/settings/TicketPermissionsPanel.vue'
import AppUsersPanel from '@/components/settings/AppUsersPanel.vue'
import TestMailPanel from '@/components/settings/TestMailPanel.vue'
import AuditLogPanel from '@/components/AuditLogPanel.vue'
import ActiveSessionsPanel from '@/components/settings/ActiveSessionsPanel.vue'

const SECTIONS = ['general', 'microsoft', 'session', 'sessions', 'companies', 'groups', 'permissions', 'app-users', 'testmail', 'audit'] as const
type Section = typeof SECTIONS[number]

const route  = useRoute()
const router = useRouter()
const { toast } = useToast()
const { state: saveState, save: doSave, reset: doReset } = useSettingsSaveBar()

function sectionFromRoute(): Section {
  const s = route.query.section
  return (typeof s === 'string' && (SECTIONS as readonly string[]).includes(s)) ? (s as Section) : 'general'
}
const active = ref<Section>(sectionFromRoute())
// URL → aktive Sektion (Deep-Link + Browser Vor/Zurück)
watch(() => route.query.section, () => { active.value = sectionFromRoute() })

// ── Nav ──────────────────────────────────────────────────────────────────────
const nav = [
  { key: 'general',     label: 'Allgemein',          group: 'System' },
  { key: 'microsoft',   label: 'Microsoft OAuth',    group: 'System' },
  { key: 'session',     label: 'Session & Security', group: 'System' },
  { key: 'sessions',    label: 'Aktive Sessions',    group: 'System' },
  { key: 'audit',       label: 'Audit-Log',          group: 'System' },
  { key: 'companies',   label: 'Firmen',             group: 'Organisation' },
  { key: 'groups',      label: 'Fachabteilungen',    group: 'Organisation' },
  { key: 'permissions', label: 'Erstellrechte',      group: 'Berechtigungen' },
  { key: 'app-users',   label: 'Benutzer & Rollen',  group: 'Berechtigungen' },
  { key: 'testmail',    label: 'Testmail',           group: 'Kommunikation' },
] as const

const navGroups = computed(() => {
  const g: Record<string, typeof nav[number][]> = {}
  nav.forEach(n => { (g[n.group] ??= []).push(n) })
  return g
})

// Sektionswechsel über die URL (dadurch funktioniert Browser Vor/Zurück).
// `item` wird bewusst fallen gelassen – die neue Sektion startet in der Liste.
// Klick auf den bereits aktiven Reiter im Detail → zurück zur Übersicht.
function switchTo(key: Section) {
  if (key === active.value) {
    if (route.query.item !== undefined) router.push({ query: { section: key } })
    return
  }
  router.push({ query: { section: key } })
}

// Unsaved-Guard – greift auch beim Browser-Zurück (Query-Wechsel = Route-Update).
onBeforeRouteUpdate((to, from) => {
  if (to.query.section !== from.query.section && saveState.dirty) {
    if (!confirm('Es gibt ungespeicherte Änderungen. Verwerfen und Sektion wechseln?')) return false
  }
  return true
})

// Warnung beim Verlassen der Seite mit ungespeicherten Änderungen.
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (saveState.dirty) { e.preventDefault(); e.returnValue = '' }
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onUnmounted(() => window.removeEventListener('beforeunload', onBeforeUnload))
</script>

<template>
  <AppLayout title="Admin · Settings">

    <Transition enter-active-class="transition duration-200" enter-from-class="opacity-0 translate-y-2"
                leave-active-class="transition duration-150" leave-to-class="opacity-0">
      <div v-if="toast"
           class="fixed top-6 right-6 z-50 rounded-xl border px-4 py-3 text-sm shadow-lg"
           :class="toast.ok
             ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
             : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
        {{ toast.msg }}
      </div>
    </Transition>

    <div class="flex gap-5 min-h-[600px]">

      <!-- Sidebar -->
      <aside class="w-56 flex-shrink-0">
        <nav class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                    rounded-2xl shadow-sm p-3 space-y-4 sticky top-4">
          <template v-for="(items, group) in navGroups" :key="group">
            <div>
              <p class="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-gray-400">{{ group }}</p>
              <button v-for="item in items" :key="item.key"
                      @click="switchTo(item.key as Section)"
                      class="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition text-left"
                      :class="active === item.key
                        ? 'bg-[#3EAAB8] text-white font-medium'
                        : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'">
                {{ item.label }}
              </button>
            </div>
          </template>
        </nav>
      </aside>

      <!-- Content -->
      <div class="flex-1 min-w-0">
        <div class="space-y-6">
          <EnvInfoPanel            v-if="active === 'general'"      variant="general" />
          <EnvInfoPanel            v-else-if="active === 'microsoft'" variant="microsoft" />
          <EnvInfoPanel            v-else-if="active === 'session'"  variant="session" />
          <ActiveSessionsPanel     v-else-if="active === 'sessions'" />
          <CompaniesPanel          v-else-if="active === 'companies'" />
          <DepartmentsPanel        v-else-if="active === 'groups'" />
          <TicketPermissionsPanel  v-else-if="active === 'permissions'" />
          <AppUsersPanel           v-else-if="active === 'app-users'" />
          <AuditLogPanel           v-else-if="active === 'audit'" />
          <TestMailPanel           v-else-if="active === 'testmail'" />
        </div>

        <!-- Sticky Speicher-Leiste (scrollt mit, unten) -->
        <div v-if="saveState.dirty" class="sticky bottom-4 z-30 mt-6">
          <div class="flex items-center justify-between gap-3 rounded-2xl border border-[#3EAAB8]/40
                      bg-white/95 dark:bg-[#212B3A]/95 backdrop-blur shadow-lg px-4 py-3">
            <span class="text-sm font-medium text-gray-700 dark:text-gray-200">
              ● Ungespeicherte Änderungen
            </span>
            <div class="flex gap-2">
              <button @click="doReset()" :disabled="saveState.saving" class="btn-secondary">Verwerfen</button>
              <button @click="doSave()" :disabled="saveState.saving" class="btn-primary">
                {{ saveState.saving ? 'Speichert…' : 'Speichern' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
