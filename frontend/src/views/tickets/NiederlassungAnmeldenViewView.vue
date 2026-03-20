

<!-- ── NiederlassungAnmeldenViewView.vue ──────────────────────────────────── -->
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

const miete = (k: string) => data.value?.description?.miete?.[k]    ?? '—'
const it    = (k: string) => data.value?.description?.it?.[k]       ?? '—'
const m     = (k: string) => data.value?.description?.marketing?.[k] ?? '—'
const f     = (k: string) => data.value?.description?.fuhrpark?.[k]  ?? '—'

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
  router.push(`/tickets/edit/niederlassung-anmelden/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Niederlassung anmelden">
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
            <div><p class="ro-label">Status</p><p class="font-medium text-gray-900 dark:text-white">{{ STATUS_LABEL[data.ticket.status] ?? data.ticket.status }}</p></div>
            <div><p class="ro-label">Priorität</p><p class="font-medium text-gray-900 dark:text-white">{{ PRIORITY_LABEL[data.ticket.priority] ?? data.ticket.priority }}</p></div>
            <div><p class="ro-label">Antragsteller</p><p class="font-medium text-gray-900 dark:text-white">{{ data.ticket.owner_name }}</p></div>
            <div class="pt-3 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <div><p class="ro-label">Verantwortlicher</p><p class="text-gray-900 dark:text-white">{{ data.ticket.accountable_name || '—' }}</p></div>
              <div v-if="data.ticket.comment"><p class="ro-label">Kommentar</p><p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ data.ticket.comment }}</p></div>
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

          <!-- Niederlassung -->
          <div class="card space-y-4">
            <h2 class="section-title">Niederlassung</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Ort</p><p class="ro-value">{{ miete('location') }}</p></div>
              <div><p class="ro-label">Firma</p><p class="ro-value">{{ miete('company') }}</p></div>
              <div><p class="ro-label">Wiedereröffnung</p><p class="ro-value">{{ miete('reopening') }}</p></div>
              <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ miete('cost_center') }}</p></div>
              <div><p class="ro-label">Startdatum</p><p class="ro-value">{{ miete('start_date') }}</p></div>
              <div>
                <p class="ro-label">Firma an Klingel sichtbar?</p>
                <p class="ro-value">{{ miete('sign_visible') }}</p>
                <p v-if="miete('sign_visible') === 'Nein'" class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                  📌 Bitte Zettel oder ähnliches anbringen.
                </p>
              </div>
              <div class="md:col-span-2"><p class="ro-label">Adresse</p><p class="ro-value whitespace-pre-wrap">{{ miete('address') }}</p></div>
              <div><p class="ro-label">Vorgesetzter Niederlassung</p><p class="ro-value">{{ miete('location_supervisor_name') }}</p></div>
              <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ miete('contact_person_name') }}</p></div>
            </div>
          </div>

          <!-- IT -->
          <div class="card space-y-4">
            <h2 class="section-title">IT</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Serverschrank vorhanden?</p><p class="ro-value">{{ it('server_rack') }}</p></div>
              <div><p class="ro-label">Netzwerkverkabelung</p><p class="ro-value">{{ it('network_cabling') }}</p></div>
              <div class="md:col-span-2"><p class="ro-label">DSL/Glasfaser-Dose installiert?</p><p class="ro-value">{{ it('line_installed') }}</p></div>
              <template v-if="it('line_installed') === 'Ja'">
                <div><p class="ro-label">Art / Anschluss</p><p class="ro-value">{{ it('line_type') }}</p></div>
                <div class="md:col-span-2"><p class="ro-label">Standort</p><p class="ro-value whitespace-pre-wrap">{{ it('line_location') }}</p></div>
              </template>
              <template v-if="it('line_installed') === 'Nein'">
                <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  📌 Vermieter wird mit der Installation beauftragt.
                </div>
                <div><p class="ro-label">Vermieter – Name</p><p class="ro-value">{{ it('landlord_name') }}</p></div>
                <div><p class="ro-label">Vermieter – Kontakt</p><p class="ro-value">{{ it('landlord_contact') }}</p></div>
              </template>
            </div>
          </div>

          <!-- Marketing -->
          <div class="card space-y-2">
            <h2 class="section-title">Marketing</h2>
            <p class="ro-label">Öffnungszeiten</p>
            <p class="ro-value whitespace-pre-wrap">{{ m('opening_hours') }}</p>
          </div>

          <!-- Fuhrpark -->
          <div class="card space-y-4">
            <h2 class="section-title">Fuhrpark</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Poolfahrzeuge benötigt?</p><p class="ro-value">{{ f('pool_cars') }}</p></div>
              <div v-if="f('pool_cars') === 'Ja'"><p class="ro-label">Benötigt ab</p><p class="ro-value">{{ f('pool_cars_from') }}</p></div>
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