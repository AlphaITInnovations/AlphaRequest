<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'

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
const ANLASS_LABEL: Record<string, string> = {
  kundentermin: 'Kundentermin',
  besuch_niederlassung: 'Besuch Niederlassung',
  sonstiges: 'Sonstiges',
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

const b = (k: string) => data.value?.description?.buchung?.[k] ?? '—'
</script>

<template>
  <AppLayout title="Fachabteilung – Hotelbuchung">
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

        <!-- ── Meta Sidebar ── -->
        <aside class="space-y-4">
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 space-y-4 text-sm">
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
          </div>

          <!-- Department Status -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-5 text-sm">
            <p class="ro-label mb-2">Fachabteilung</p>
            <p class="font-semibold text-[#3EAAB8] mb-2">{{ data.department.name }}</p>
            <p class="ro-label mb-1">Bearbeitungsstatus</p>
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

        <!-- ── Content ── -->
        <section class="lg:col-span-2 space-y-5">

          <!-- Antragsteller -->
          <div class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Antragsteller</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Name</p><p class="ro-value">{{ b('antragsteller_name') }}</p></div>
              <div><p class="ro-label">E-Mail</p><p class="ro-value">{{ b('antragsteller_email') }}</p></div>
              <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ b('niederlassung') }}</p></div>
              <div><p class="ro-label">Telefonnummer</p><p class="ro-value">{{ b('telefonnummer') }}</p></div>
              <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ b('kostenstelle') }}</p></div>
            </div>
          </div>

          <!-- Reisedaten -->
          <div class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Reisedaten</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div><p class="ro-label">Anreisedatum</p><p class="ro-value">{{ b('anreisedatum') }}</p></div>
              <div><p class="ro-label">Abreisedatum</p><p class="ro-value">{{ b('abreisedatum') }}</p></div>
              <div><p class="ro-label">Übernachtungen</p><p class="ro-value">{{ b('anzahl_naechte') }}</p></div>
            </div>
          </div>

          <!-- Reiseziel -->
          <div class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Reiseziel</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Ort / Stadt</p><p class="ro-value">{{ b('ort_stadt') }}</p></div>
              <div><p class="ro-label">Partner-Hotel</p><p class="ro-value">{{ b('partner_hotel') }}</p></div>
              <div class="md:col-span-2"><p class="ro-label">Hotelwunsch</p><p class="ro-value">{{ b('hotelwunsch') }}</p></div>
            </div>
          </div>

          <!-- Reiseanlass -->
          <div class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Reiseanlass</h2>
            <div>
              <p class="ro-label">Art</p>
              <p class="ro-value font-medium">{{ ANLASS_LABEL[b('reiseanlass')] ?? b('reiseanlass') }}</p>
            </div>

            <!-- Kundentermin -->
            <template v-if="b('reiseanlass') === 'kundentermin'">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                <div><p class="ro-label">Kundenname</p><p class="ro-value">{{ b('kunde_name') }}</p></div>
                <div><p class="ro-label">Anschrift</p><p class="ro-value">{{ b('kunde_anschrift') }}</p></div>
                <div class="md:col-span-2"><p class="ro-label">Grund des Besuchs</p><p class="ro-value whitespace-pre-wrap">{{ b('kunde_grund') }}</p></div>
              </div>
            </template>

            <!-- Besuch NL -->
            <template v-if="b('reiseanlass') === 'besuch_niederlassung'">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ b('besuch_niederlassung') }}</p></div>
                <div class="md:col-span-2" v-if="b('besuch_begruendung') !== '—'"><p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('besuch_begruendung') }}</p></div>
              </div>
            </template>

            <!-- Sonstiges -->
            <template v-if="b('reiseanlass') === 'sonstiges'">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                <div class="md:col-span-2"><p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('sonstiges_grund') }}</p></div>
                <div><p class="ro-label">Genehmigung durch</p><p class="ro-value">{{ b('genehmigung_name') }}</p></div>
              </div>
            </template>
          </div>

          <!-- Budgetvorgaben -->
          <div class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Budgetvorgaben</h2>
            <div>
              <p class="ro-label">Bestätigung</p>
              <p class="ro-value font-medium">
                {{ b('budget_bestaetigung') === 'unter_120' ? 'Kosten ≤ 120 € pro Nacht inkl. Frühstück' : b('budget_bestaetigung') === 'abweichung' ? 'Abweichung erforderlich' : '—' }}
              </p>
            </div>
            <template v-if="b('budget_bestaetigung') === 'abweichung'">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                <div class="md:col-span-2"><p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ b('budget_begruendung') }}</p></div>
                <div><p class="ro-label">Genehmigung durch</p><p class="ro-value">{{ b('budget_genehmigung_name') }}</p></div>
              </div>
            </template>
          </div>

          <!-- Besondere Anforderungen -->
          <div v-if="b('besondere_anforderungen') !== '—'" class="card space-y-4">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Besondere Anforderungen</h2>
            <p class="text-sm text-gray-900 dark:text-white whitespace-pre-wrap">{{ b('besondere_anforderungen') }}</p>
          </div>

        </section>
      </div>

      <!-- Action Bar -->
      <TicketActionBar
        phase="view"
        :loading="submitting"
        :department-name="data.department.name"
        :department-status="data.department.status"
        :can-complete="data.department.can_complete"
        @department-done="markDone"
      />
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
.card { @apply bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09] rounded-2xl shadow-sm p-6; }
</style>