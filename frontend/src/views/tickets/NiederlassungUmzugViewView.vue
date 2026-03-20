
<!-- ── NiederlassungUmzugViewView.vue ─────────────────────────────────────── -->
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

const LEASE_LABEL: Record<string, string> = {
  cancel: 'Wird gekündigt',
  keep:   'Bleibt bestehen',
}

const ma  = (k: string) => data.value?.description?.miete_alt?.[k]  ?? '—'
const mn  = (k: string) => data.value?.description?.miete_neu?.[k]  ?? '—'
const ia  = (k: string) => data.value?.description?.it_alt?.[k]     ?? '—'
const inn = (k: string) => data.value?.description?.it_neu?.[k]     ?? '—'
const m   = (k: string) => data.value?.description?.marketing?.[k]  ?? '—'
const f   = (k: string) => data.value?.description?.fuhrpark?.[k]   ?? '—'

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
  router.push(`/tickets/edit/niederlassung-umzug/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Niederlassung umziehen">
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

          <!-- Miete -->
          <div class="card space-y-6">
            <h2 class="section-title">Miete</h2>

            <!-- Alt -->
            <div class="space-y-3">
              <h3 class="subsection">Alt (bisherige Niederlassung)</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Ort (alt)</p><p class="ro-value">{{ ma('location') }}</p></div>
                <div><p class="ro-label">Firma (alt)</p><p class="ro-value">{{ ma('company') }}</p></div>
                <div class="md:col-span-2">
                  <p class="ro-label">Mietvertrag</p>
                  <p class="ro-value">{{ LEASE_LABEL[ma('lease_action')] ?? ma('lease_action') }}</p>
                </div>
                <div v-if="ma('lease_action') === 'cancel'">
                  <p class="ro-label">Kündigungsdatum</p><p class="ro-value">{{ ma('lease_cancel_date') }}</p>
                </div>
                <div v-if="ma('lease_action') === 'keep'" class="md:col-span-2">
                  <p class="ro-label">Begründung</p><p class="ro-value whitespace-pre-wrap">{{ ma('lease_keep_reason') }}</p>
                </div>
              </div>
            </div>

            <!-- Neu -->
            <div class="pt-5 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <h3 class="subsection">Neu (neue Niederlassung)</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Ort (neu)</p><p class="ro-value">{{ mn('location') }}</p></div>
                <div><p class="ro-label">Firma (neu)</p><p class="ro-value">{{ mn('company') }}</p></div>
                <div>
                  <p class="ro-label">Firma an Klingel sichtbar?</p>
                  <p class="ro-value">{{ mn('sign_visible') }}</p>
                  <p v-if="mn('sign_visible') === 'Nein'" class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">📌 Zettel anbringen</p>
                </div>
                <div><p class="ro-label">Wiedereröffnung</p><p class="ro-value">{{ mn('reopening') }}</p></div>
                <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ mn('cost_center') }}</p></div>
                <div><p class="ro-label">Startdatum</p><p class="ro-value">{{ mn('start_date') }}</p></div>
                <div class="md:col-span-2"><p class="ro-label">Adresse</p><p class="ro-value whitespace-pre-wrap">{{ mn('address') }}</p></div>
                <div><p class="ro-label">Vorgesetzter</p><p class="ro-value">{{ mn('location_supervisor_name') }}</p></div>
                <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ mn('contact_person_name') }}</p></div>
              </div>
            </div>
          </div>

          <!-- IT -->
          <div class="card space-y-6">
            <h2 class="section-title">IT</h2>

            <!-- Alt -->
            <div class="space-y-3">
              <h3 class="subsection">Alt</h3>
              <template v-if="ma('lease_action') === 'cancel'">
                <div class="rounded-xl border border-red-300/60 bg-red-50 dark:bg-red-900/20 p-4 space-y-2">
                  <p class="text-sm font-semibold text-red-800 dark:text-red-200">⚠️ Wichtige Hinweise</p>
                  <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
                    <span>{{ ia('confirm_dsl_cancel') ? '✅' : '⬜' }}</span>
                    <div><strong>DSL/Internet gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_dsl_cancel') ? 'Ja' : 'Nein' }}</p></div>
                  </div>
                  <div class="flex items-start gap-2 text-sm text-red-800 dark:text-red-200">
                    <span>{{ ia('confirm_landline_cancel') ? '✅' : '⬜' }}</span>
                    <div><strong>Festnetz gekündigt</strong><p class="text-xs opacity-75">Bestätigt: {{ ia('confirm_landline_cancel') ? 'Ja' : 'Nein' }}</p></div>
                  </div>
                </div>
              </template>
            </div>

            <!-- Neu -->
            <div class="pt-4 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
              <h3 class="subsection">Neu</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Serverschrank vorhanden?</p><p class="ro-value">{{ inn('server_rack') }}</p></div>
                <div><p class="ro-label">Netzwerkverkabelung</p><p class="ro-value">{{ inn('network_cabling') }}</p></div>
                <div class="md:col-span-2"><p class="ro-label">DSL/Glasfaser-Dose installiert?</p><p class="ro-value">{{ inn('line_installed') }}</p></div>
                <template v-if="inn('line_installed') === 'Ja'">
                  <div><p class="ro-label">Art / Anschluss</p><p class="ro-value">{{ inn('line_type') }}</p></div>
                  <div class="md:col-span-2"><p class="ro-label">Standort</p><p class="ro-value whitespace-pre-wrap">{{ inn('line_location') }}</p></div>
                </template>
                <template v-if="inn('line_installed') === 'Nein'">
                  <div class="md:col-span-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                    📌 Vermieter wird mit der Installation beauftragt.
                  </div>
                  <div><p class="ro-label">Vermieter – Name</p><p class="ro-value">{{ inn('landlord_name') }}</p></div>
                  <div><p class="ro-label">Vermieter – Kontakt</p><p class="ro-value">{{ inn('landlord_contact') }}</p></div>
                </template>
              </div>
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
.subsection    { @apply text-sm font-semibold text-gray-600 dark:text-gray-400; }
.ro-label      { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value      { @apply text-sm text-gray-900 dark:text-white; }
</style>