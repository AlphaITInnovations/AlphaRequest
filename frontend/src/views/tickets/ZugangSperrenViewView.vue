

<!-- ── ZugangSperrenViewView.vue ──────────────────────────────────────────── -->
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

const p  = (k: string) => data.value?.description?.personal?.[k] ?? '—'
const it = (k: string) => data.value?.description?.it?.[k]       ?? '—'
const f  = (k: string) => data.value?.description?.fuhrpark?.[k] ?? '—'

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
  router.push(`/tickets/edit/zugang-sperren/${ticketId}`)
}
</script>

<template>
  <AppLayout title="Fachabteilung – Offboarding">
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

          <!-- Basisdaten -->
          <div class="card space-y-4">
            <h2 class="section-title">Basisdaten</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Vorname</p><p class="ro-value">{{ p('first_name') }}</p></div>
              <div><p class="ro-label">Nachname</p><p class="ro-value">{{ p('last_name') }}</p></div>
              <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ p('cost_center') }}</p></div>
              <div><p class="ro-label">Firma lt. Arbeitsvertrag</p><p class="ro-value">{{ p('contract_company') }}</p></div>
              <div><p class="ro-label">Austrittsdatum</p><p class="ro-value">{{ p('exit_date') }}</p></div>
              <div><p class="ro-label">Abfindungsvereinbarung</p><p class="ro-value">{{ p('severance_agreement') }}</p></div>
            </div>
          </div>

          <!-- IT -->
          <div class="card space-y-5">
            <h2 class="section-title">IT</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <p class="ro-label">Mailweiterleitung?</p>
                <p class="ro-value">{{ it('mail_forwarding') }}</p>
              </div>
              <div>
                <p class="ro-label">Weiterleiten an</p>
                <p class="ro-value">{{ it('mail_forwarding') === 'Ja' ? it('mail_forward_to') : '—' }}</p>
              </div>
              <div>
                <p class="ro-label">Postfachzugriff gewähren?</p>
                <p class="ro-value">{{ it('mailbox_access') }}</p>
              </div>
              <div class="md:col-span-2">
                <p class="ro-label">Zugriff für</p>
                <p class="ro-value whitespace-pre-wrap">{{ it('mailbox_access') === 'Ja' ? it('mailbox_access_for') : '—' }}</p>
              </div>
              <div>
                <p class="ro-label">Abwesenheitsnotiz?</p>
                <p class="ro-value">{{ it('auto_reply') }}</p>
              </div>
              <div class="md:col-span-2">
                <p class="ro-label">Text der Abwesenheitsnotiz</p>
                <p class="ro-value whitespace-pre-wrap font-mono text-xs">{{ it('auto_reply') === 'Ja' ? it('auto_reply_text') : '—' }}</p>
              </div>
            </div>

            <!-- Hinweis-Box -->
            <div class="rounded-xl border border-amber-300/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              <p class="font-semibold mb-1">📌 Wichtige Hinweise</p>
              <ul class="list-disc pl-4 space-y-1">
                <li><strong>Mailweiterleitung</strong> und <strong>Postfachzugriff</strong> sind jeweils <strong>maximal 30 Tage</strong> möglich.</li>
                <li>Postfächer werden gesichert – <strong>neue E-Mails werden nicht mehr zugestellt.</strong></li>
                <li>Abwesenheitsnotiz ggf. Platzhalter prüfen: <code>&lt;Name&gt;</code>, <code>&lt;Ersatzmailadresse&gt;</code></li>
              </ul>
            </div>
          </div>

          <!-- Fuhrpark -->
          <div class="card space-y-4">
            <h2 class="section-title">Fuhrpark</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><p class="ro-label">Dienstwagen vorhanden?</p><p class="ro-value">{{ f('car') }}</p></div>
              <div><p class="ro-label">Rückgabedatum</p><p class="ro-value">{{ f('car') === 'Ja' ? f('car_return_date') : '—' }}</p></div>
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