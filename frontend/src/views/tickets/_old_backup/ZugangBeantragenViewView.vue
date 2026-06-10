<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import ZugangBeantragenContentPanel from '@/components/tickets/ZugangBeantragenContentPanel.vue'

const route  = useRoute()
const router = useRouter()

const ticketId     = Number(route.params.id)
const departmentId = route.query.department as string

const loading    = ref(true)
const submitting = ref(false)
const data       = ref<any>(null)

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}
const DEPT_STATUS_LABEL: Record<string, string> = {
  done: 'Ausgeführt', rejected: 'Abgelehnt', skipped: 'Übersprungen',
  open: 'Offen', in_progress: 'In Bearbeitung',
}

onMounted(async () => {
  try {
    const res = await client.get(`/tickets/${ticketId}/view`, {
      params: { department: departmentId }
    })
    data.value = res.data.data
  } catch {
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
})

async function markDone() {
  submitting.value = true
  try {
    await client.patch(`/tickets/${ticketId}/departments/${departmentId}`, { status: 'done' })
    router.push('/dashboard')
  } catch {
    alert('Fehler beim Abschließen')
  } finally {
    submitting.value = false
  }
}

function goToEdit() {
  const ok = confirm(
    '⚠️ Achtung\n\nIn dieser Phase soll das Ticket nur im Notfall bearbeitet werden.\n\nMöchten Sie wirklich fortfahren?'
  )
  if (!ok) return
  router.push(`/tickets/edit/${data.value.ticket.ticket_type}/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Auftrag">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6 pb-24">

      <!-- Header -->
      <div>
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
          {{ data.ticket.title }}
        </h1>
        <p class="text-sm text-gray-400 mt-1">Erstellt am {{ data.ticket.created_at }}</p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

        <!-- Meta Sidebar -->
        <aside class="space-y-4">
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 space-y-4 text-sm">
            <div>
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Status</p>
              <p class="font-medium text-gray-900 dark:text-white">
                {{ STATUS_LABEL[data.ticket.status] ?? data.ticket.status }}
              </p>
            </div>
            <div>
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Priorität</p>
              <p class="font-medium text-gray-900 dark:text-white">
                {{ PRIORITY_LABEL[data.ticket.priority] ?? data.ticket.priority }}
              </p>
            </div>
            <div>
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Antragsteller</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.ticket.owner_name }}</p>
            </div>
            <div class="pt-3 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <div>
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Verantwortlicher</p>
                <p class="text-gray-900 dark:text-white">{{ data.ticket.accountable_name || '—' }}</p>
              </div>
              <div v-if="data.ticket.comment">
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Kommentar</p>
                <p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ data.ticket.comment }}</p>
              </div>
            </div>
          </div>

          <!-- Department Status Card -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Fachabteilung</p>
            <p class="font-semibold text-[#3EAAB8] mb-2">{{ data.department.name }}</p>
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Bearbeitungsstatus</p>
            <span class="inline-flex items-center gap-1.5 text-sm font-medium"
                  :class="{
                    'text-green-600':  data.department.status === 'done',
                    'text-red-500':    data.department.status === 'rejected',
                    'text-[#3EAAB8]':  ['open','in_progress'].includes(data.department.status),
                  }">
              {{ DEPT_STATUS_LABEL[data.department.status] ?? data.department.status }}
            </span>
          </div>
        </aside>

        <!-- Content -->
        <section class="lg:col-span-2 space-y-5">
          <ZugangBeantragenContentPanel :description="data.description" />
        </section>
      </div>

      <TicketActionBar
        phase="view"
        :loading="submitting"
        :department-name="data.department.name"
        :department-status="data.department.status"
        :can-complete="data.department.can_complete"
        @department-done="markDone"
        @department-edit="goToEdit"
      />
    </div>
  </AppLayout>
</template>