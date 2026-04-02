<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'

const route        = useRoute()
const router       = useRouter()
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

const s  = (k: string) => data.value?.description?.stelle?.[k] ?? '—'
const sa = (k: string): string[] => {
  const v = data.value?.description?.stelle?.[k]
  return Array.isArray(v) ? v : []
}

onMounted(async () => {
  try {
    const res = await client.get(`/tickets/${ticketId}/view`, { params: { department: departmentId } })
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
  if (!confirm('⚠️ Achtung\n\nIn dieser Phase soll das Ticket nur im Notfall bearbeitet werden.\n\nMöchten Sie wirklich fortfahren?')) return
  router.push(`/tickets/edit/marketing-stellenanzeige/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Stellenanzeige">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6 pb-24">

      <div>
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">{{ data.ticket.title }}</h1>
        <p class="text-sm text-gray-400 mt-1">Erstellt am {{ data.ticket.created_at }}</p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

        <!-- Sidebar -->
        <aside class="space-y-4">
          <div class="card space-y-4 text-sm">
            <div><p class="ro-label">Status</p><p class="ro-value">{{ STATUS_LABEL[data.ticket.status] ?? data.ticket.status }}</p></div>
            <div><p class="ro-label">Priorität</p><p class="ro-value">{{ PRIORITY_LABEL[data.ticket.priority] ?? data.ticket.priority }}</p></div>
            <div><p class="ro-label">Antragsteller</p><p class="ro-value">{{ data.ticket.owner_name }}</p></div>
            <div class="pt-3 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <div><p class="ro-label">Verantwortlicher</p><p class="ro-value">{{ data.ticket.accountable_name || '—' }}</p></div>
              <div v-if="data.ticket.comment"><p class="ro-label">Kommentar</p><p class="ro-value whitespace-pre-wrap">{{ data.ticket.comment }}</p></div>
            </div>
          </div>

          <div class="card text-sm">
            <p class="ro-label mb-2">Fachabteilung</p>
            <p class="font-semibold text-[#3EAAB8] mb-3">{{ data.department.name }}</p>
            <p class="ro-label mb-1">Bearbeitungsstatus</p>
            <span class="text-sm font-medium"
                  :class="{
                    'text-green-600': data.department.status === 'done',
                    'text-red-500':   data.department.status === 'rejected',
                    'text-[#3EAAB8]': ['open','in_progress'].includes(data.department.status),
                  }">
              {{ DEPT_STATUS_LABEL[data.department.status] ?? data.department.status }}
            </span>
          </div>
        </aside>

        <!-- Content -->
        <section class="lg:col-span-2 space-y-5">

          <!-- Freigabe -->
          <div class="card space-y-3">
            <h2 class="section-title">✅ Freigabe</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Freigabe erteilt durch</p><p class="ro-value">{{ s('freigabe_name') }}</p></div>
              <div><p class="ro-label">E-Mail</p><p class="ro-value">{{ s('freigabe_email') }}</p></div>
            </div>
          </div>

          <!-- Niederlassung & Gesellschaft -->
          <div class="card space-y-3">
            <h2 class="section-title">🏢 Niederlassung & Gesellschaft</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ s('niederlassung') }}</p></div>
              <div>
                <p class="ro-label">Gesellschaft</p>
                <!-- gesellschaft ist jetzt ein String (war früher Array gesellschaften) -->
                <p class="ro-value">{{ s('gesellschaft') }}</p>
              </div>
            </div>
          </div>

          <!-- Stelle -->
          <div class="card space-y-3">
            <h2 class="section-title">💼 Stelle</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="md:col-span-2"><p class="ro-label">Berufsbezeichnung</p><p class="ro-value">{{ s('berufsbezeichnung') }}</p></div>
              <div><p class="ro-label">Beschäftigungsart</p><p class="ro-value">{{ s('beschaeftigungsart') }}</p></div>
              <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ s('kostenstelle') }}</p></div>
              <div class="md:col-span-2"><p class="ro-label">Talention-Verantwortlicher</p><p class="ro-value">{{ s('talention_verantwortlicher_name') }}</p></div>
            </div>
          </div>

          <!-- Benefits & Details -->
          <div class="card space-y-4">
            <h2 class="section-title">⭐ Benefits & Details</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="md:col-span-2"><p class="ro-label">Benefits</p><p class="ro-value whitespace-pre-wrap">{{ s('benefits') }}</p></div>
              <div><p class="ro-label">Gehaltsangabe gewünscht</p><p class="ro-value">{{ s('gehaltsangabe') }}</p></div>
              <div v-if="s('gehaltsangabe') === 'Ja'"><p class="ro-label">Gehalt</p><p class="ro-value">{{ s('gehalt') }}</p></div>
              <div class="md:col-span-2"><p class="ro-label">Notwendige Bedingungen</p><p class="ro-value whitespace-pre-wrap">{{ s('bedingungen_notwendig') }}</p></div>
              <div class="md:col-span-2" v-if="s('qualifikationen_nice') !== '—'">
                <p class="ro-label">Wünschenswerte Qualifikationen</p>
                <p class="ro-value whitespace-pre-wrap">{{ s('qualifikationen_nice') }}</p>
              </div>
            </div>
          </div>

          <!-- Anzeige -->
          <div class="card space-y-3">
            <h2 class="section-title">📅 Anzeige</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Online ab</p><p class="ro-value">{{ s('online_datum') }}</p></div>
              <div><p class="ro-label">Open End</p><p class="ro-value">{{ s('open_end') }}</p></div>
              <div v-if="s('open_end') === 'Nein'"><p class="ro-label">Enddatum</p><p class="ro-value">{{ s('end_datum') }}</p></div>
              <div><p class="ro-label">Städte</p><p class="ro-value">{{ s('staedte') }}</p></div>
              <div><p class="ro-label">Radius</p><p class="ro-value">{{ s('radius') }}</p></div>
              <div><p class="ro-label">Max. Budget / Monat</p><p class="ro-value">{{ s('budget') }} €</p></div>
            </div>
          </div>

          <!-- Funnel -->
          <div class="card space-y-4">
            <h2 class="section-title">🎯 Funnel</h2>
            <div>
              <p class="ro-label mb-2">Vorqualifizierungsfragen</p>
              <ul v-if="sa('vorqualifizierung_fragen').length || sa('vorqualifizierung_custom').length"
                  class="space-y-1.5">
                <li v-for="f in sa('vorqualifizierung_fragen')" :key="f"
                    class="flex items-start gap-2 text-sm text-gray-900 dark:text-white">
                  <span class="text-[#3EAAB8] mt-0.5">✓</span> {{ f }}
                </li>
                <li v-for="f in sa('vorqualifizierung_custom')" :key="f"
                    class="flex items-start gap-2 text-sm text-gray-900 dark:text-white">
                  <span class="text-[#3EAAB8] mt-0.5">✓</span> {{ f }}
                </li>
              </ul>
              <p v-else class="ro-value">—</p>
            </div>
            <div>
              <p class="ro-label">FAQ</p>
              <p class="ro-value whitespace-pre-wrap">{{ s('faq') }}</p>
            </div>
          </div>

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

<style scoped>
@reference "../../style.css";
.card          { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-5; }
.section-title { @apply text-base font-semibold text-[#3EAAB8] mb-1; }
.ro-label      { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value      { @apply text-sm text-gray-900 dark:text-white; }
</style>