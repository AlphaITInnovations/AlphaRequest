<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { client } from '@/api/client'

// Read-only Anzeige der .env-Werte. `variant` wählt den Block (general/microsoft/session).
const props = defineProps<{ variant: 'general' | 'microsoft' | 'session' }>()

const env = ref<any>(null)
onMounted(async () => {
  const { data } = await client.get('/settings/env')
  env.value = data.data
})

const TITLE: Record<string, string> = {
  general: 'Allgemein', microsoft: 'Microsoft OAuth', session: 'Session & Security',
}
const rows = computed<Record<string, any> | null>(() => env.value?.[props.variant] ?? null)

const ENV_DESCS: Record<string, string> = {
  APP_ENV: 'Laufzeitumgebung (z. B. development/production)',
  PORT: 'HTTP-Port, auf dem die App lauscht',
  HTTPS: 'Aktiviert HTTPS',
  TICKET_MAIL: 'Fallback-Mailbox für Benachrichtigungen',
  CLIENT_ID: 'App-Registrierung (öffentliche ID)',
  CLIENT_SECRET: 'App-Geheimnis (niemals anzeigen)',
  TENANT_ID: 'Azure AD-Tenant',
  REDIRECT_URI: 'OAuth-Redirect für Microsoft-Login',
  SCOPE: 'Gewünschte Microsoft-Scopes',
  ADMIN_GROUP_ID: 'Azure-Gruppe mit Admin-Zugriff',
  SESSION_TIMEOUT: 'Inaktivitäts-Timeout der Sitzung (Sek.)',
  SECRET_KEY: 'Signierschlüssel für Session/Cookies',
}
function envDesc(key: string) { return ENV_DESCS[key] ?? key }
function envVal(val: unknown): string { return val === null || val === undefined ? '—' : String(val) }
</script>

<template>
  <section class="space-y-4">
    <div class="rounded-xl border border-blue-200 dark:border-blue-500/30
                bg-blue-50 dark:bg-blue-900/20 px-4 py-3 text-sm text-blue-800 dark:text-blue-200">
      Diese Einstellungen werden über <strong>Umgebungsvariablen</strong> (.env) verwaltet und können hier nur eingesehen werden.
    </div>

    <h2 class="section-title">{{ TITLE[variant] }}</h2>
    <div class="card-section" v-if="rows">
      <table class="w-full text-sm">
        <thead><tr class="text-left text-xs text-gray-400 border-b dark:border-white/[0.06]">
          <th class="pb-2 pr-4">Variable</th><th class="pb-2 pr-4">Beschreibung</th><th class="pb-2">Wert / Status</th>
        </tr></thead>
        <tbody class="divide-y divide-gray-100 dark:divide-white/[0.04]">
          <tr v-for="(val, key) in rows" :key="String(key)">
            <td class="py-2.5 pr-4 font-mono text-xs text-gray-500 dark:text-gray-400">{{ key }}</td>
            <td class="py-2.5 pr-4 text-sm text-gray-600 dark:text-gray-400">{{ envDesc(String(key)) }}</td>
            <td class="py-2.5">
              <span v-if="val.sensitive" class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="val.is_set ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300' : 'bg-gray-100 text-gray-500 dark:bg-white/5'">
                {{ val.is_set ? 'gesetzt' : '—' }}
              </span>
              <span v-else class="text-sm font-medium text-gray-900 dark:text-white">{{ envVal(val.value) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
