<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import BasisTicketContentPanel from '@/components/tickets/BasisTicketContentPanel.vue'

const route    = useRoute()
const router   = useRouter()
const ticketId = Number(route.params.id)

const loading = ref(true)
const data    = ref<any>(null)

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}

onMounted(async () => {
  try {
    const res = await client.get(`/tickets/${ticketId}`)
    const t = res.data.data
    const desc = JSON.parse(t.description || '{}')
    data.value = { ...t, parsed: desc }
  } catch {
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout title="Ticket-Details">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6 pb-12">

      <!-- Header -->
      <div>
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
          {{ data.parsed?.ticket?.titel ?? data.title }}
        </h1>
        <p class="text-sm text-gray-400 mt-1">Erstellt am {{ data.created_at }}</p>
      </div>

      <div class="flex flex-col lg:flex-row gap-6">

        <!-- ── Sidebar: Meta ── -->
        <aside class="w-full lg:w-[320px] flex-shrink-0">
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 space-y-4 text-sm lg:sticky lg:top-4">
            <div>
              <p class="ro-label">Status</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ STATUS_LABEL[data.status] ?? data.status }}</p>
            </div>
            <div>
              <p class="ro-label">Priorität</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ PRIORITY_LABEL[data.priority] ?? data.priority }}</p>
            </div>
            <div>
              <p class="ro-label">Erstellt von</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.owner_name }}</p>
            </div>
            <div>
              <p class="ro-label">Verantwortlich</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.accountable_name ?? '–' }}</p>
            </div>
            <div v-if="data.comment" class="pt-3 border-t border-gray-100 dark:border-white/[0.06]">
              <p class="ro-label">Kommentar</p>
              <p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ data.comment }}</p>
            </div>
          </div>
        </aside>

        <!-- ── Content ── -->
        <section class="flex-1">
          <BasisTicketContentPanel
            :titel="data.parsed?.ticket?.titel ?? ''"
            :eintraege="data.parsed?.ticket?.eintraege ?? []"
          />
        </section>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
</style>