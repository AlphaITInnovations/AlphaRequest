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

const h  = (k: string) => data.value?.description?.hardware?.[k] ?? '—'
const m  = ()          => data.value?.description?.hardware?.monitor  ?? {}
const a  = ()          => data.value?.description?.hardware?.artikel  ?? {}

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
  if (!confirm('⚠️ Achtung\n\nIn dieser Phase soll das Ticket nur im Notfall bearbeitet werden.\n\nMöchten Sie wirklich fortfahren?')) return
  router.push(`/tickets/edit/hardware/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Hardwarebestellung">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6 pb-24">

      <!-- Header -->
      <div>
        <h1 class="text-xl font-semibold text-gray-900 dark:text-white">{{ data.ticket.title }}</h1>
        <p class="text-sm text-gray-400 mt-1">Erstellt am {{ data.ticket.created_at }}</p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

        <!-- Sidebar -->
        <aside class="space-y-4">
          <div class="card space-y-4 text-sm">
            <div>
              <p class="ro-label">Status</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ STATUS_LABEL[data.ticket.status] ?? data.ticket.status }}</p>
            </div>
            <div>
              <p class="ro-label">Priorität</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ PRIORITY_LABEL[data.ticket.priority] ?? data.ticket.priority }}</p>
            </div>
            <div>
              <p class="ro-label">Antragsteller</p>
              <p class="font-medium text-gray-900 dark:text-white">{{ data.ticket.owner_name }}</p>
            </div>
            <div class="pt-3 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <div>
                <p class="ro-label">Verantwortlicher</p>
                <p class="text-gray-900 dark:text-white">{{ data.ticket.accountable_name || '—' }}</p>
              </div>
              <div v-if="data.ticket.comment">
                <p class="ro-label">Kommentar</p>
                <p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ data.ticket.comment }}</p>
              </div>
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

          <!-- Basisdaten -->
          <div class="card space-y-4">
            <h2 class="section-title">Basisdaten</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Mitarbeitertyp</p><p class="ro-value">{{ h('mitarbeiterTyp') }}</p></div>
              <div><p class="ro-label">Vorname</p><p class="ro-value">{{ h('vorname') }}</p></div>
              <div><p class="ro-label">Nachname</p><p class="ro-value">{{ h('nachname') }}</p></div>
              <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ h('kostenstelle') }}</p></div>
              <div><p class="ro-label">Firma</p><p class="ro-value">{{ h('firma') }}</p></div>
              <div class="md:col-span-2">
                <p class="ro-label">Lieferadresse</p>
                <p class="ro-value whitespace-pre-wrap">{{ h('addr_strasse') }} {{ h('addr_nr') }}, {{ h('addr_plz') }} {{ h('addr_stadt') }}<template v-if="h('addr_tuerschild') !== '—'"><br>(Türschild: {{ h('addr_tuerschild') }})</template></p>
              </div>
              <div><p class="ro-label">Lieferung bis</p><p class="ro-value">{{ h('lieferungBis') }}</p></div>
            </div>
          </div>

          <!-- Hardware -->
          <div class="card space-y-4">
            <h2 class="section-title">Hardware</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Gerätetyp</p><p class="ro-value">{{ h('geraet') }}</p></div>
              <div>
                <p class="ro-label">Monitor</p>
                <p class="ro-value">{{ m().benoetigt ? `Ja (${m().anzahl}×)` : 'Nein' }}</p>
              </div>
              <div>
                <p class="ro-label">Dockingstation bestellen</p>
                <p class="ro-value">{{ a().Dockingstation ? 'Ja' : 'Nein' }}</p>
              </div>
              <div>
                <p class="ro-label">Dockingstation vorhanden</p>
                <p class="ro-value">{{ h('dockingVorhanden') === true || h('dockingVorhanden') === 'true' ? 'Ja' : 'Nein' }}</p>
              </div>
              <div class="md:col-span-2">
                <p class="ro-label">Zusätzliche Hardware</p>
                <p class="ro-value">
                  {{
                    [
                      a().Notebook        && 'Notebook',
                      a().MiniPC          && 'Mini-PC',
                      a().MausUndTastatur && 'Maus & Tastatur',
                      a().Headset         && 'Headset',
                      a().Webcam          && 'Webcam',
                      a().Handy           && 'Handy',
                      a().SIM             && 'SIM-Karte',
                    ].filter(Boolean).join(', ') || '—'
                  }}
                </p>
              </div>
            </div>
          </div>

          <!-- Zusatzinfos -->
          <div class="card space-y-4">
            <h2 class="section-title">Zusatzinformationen</h2>
            <div>
              <p class="ro-label">Grund der Neubestellung</p>
              <p class="ro-value whitespace-pre-wrap">{{ h('grundBestellung') }}</p>
            </div>
            <div>
              <p class="ro-label">Bemerkung</p>
              <p class="ro-value whitespace-pre-wrap">{{ h('bemerkung') }}</p>
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
.section-title { @apply text-base font-semibold text-[#3EAAB8]; }
.ro-label      { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value      { @apply text-sm text-gray-900 dark:text-white; }
</style>