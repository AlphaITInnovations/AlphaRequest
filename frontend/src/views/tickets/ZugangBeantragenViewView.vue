<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'

const route  = useRoute()
const router = useRouter()

const ticketId   = Number(route.params.id)
const departmentId = route.query.department as string

const loading  = ref(true)
const submitting = ref(false)
const data     = ref<any>(null)

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
    await client.patch(`/tickets/${ticketId}/departments/${departmentId}`, {
      status: 'done'
    })
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

// Shorthand helpers
const p   = (k: string) => data.value?.description?.personal?.[k]   ?? '—'
const it  = (k: string) => data.value?.description?.it?.[k]         ?? '—'
const sig = (k: string) => data.value?.description?.it?.signature?.[k]  ?? '—'
const tb  = (k: string) => data.value?.description?.it?.timebutler?.[k] ?? '—'
const sw  = (k: string) => data.value?.description?.it?.software?.[k]   ?? false
const mb  = (k: string) => data.value?.description?.it?.mailboxes?.[k]  ?? '—'
const f   = (k: string) => data.value?.description?.fuhrpark?.[k]   ?? '—'

const softwareList = () => {
  const items: string[] = []
  if (sw('datev'))    items.push('DATEV')
  if (sw('persopro')) items.push('PersoPro')
  if (sw('timejob'))  items.push('TimeJob')
  if (sw('swoof'))    items.push('Swoof')
  return items.length > 0 ? items.join(', ') : '—'
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

        <!-- ── Meta Sidebar ── -->
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

        <!-- ── Content ── -->
        <section class="lg:col-span-2 space-y-5">

          <!-- Basisdaten -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-6">
            <h2 class="text-base font-semibold text-[#3EAAB8]">Basisdaten</h2>

            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Stammdaten</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Vorname</p><p class="ro-value">{{ p('first_name') }}</p></div>
                <div><p class="ro-label">Nachname</p><p class="ro-value">{{ p('last_name') }}</p></div>
                <div><p class="ro-label">Titel</p><p class="ro-value">{{ p('title') }}</p></div>
                <div><p class="ro-label">Eintrittsdatum (laut Vertrag)</p><p class="ro-value">{{ p('start_date') }}</p></div>
                <div>
                  <p class="ro-label">Straße (Privatadresse)</p>
                  <p class="ro-value">{{ p('private_street') || p('private_address') }}</p>
                </div>
                <div><p class="ro-label">PLZ</p><p class="ro-value">{{ p('private_zip') }}</p></div>
                <div><p class="ro-label">Ort</p><p class="ro-value">{{ p('private_city') }}</p></div>
                <div><p class="ro-label">Homeoffice</p><p class="ro-value">{{ p('homeoffice') }}</p></div>
                <div><p class="ro-label">Arbeitszeit (Std./Woche)</p><p class="ro-value">{{ p('weekly_hours') }}</p></div>
                <div><p class="ro-label">Personalnummer</p><p class="ro-value font-mono">{{ p('personal_number') }}</p></div>
              </div>
            </div>

            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Organisation</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p class="ro-label">Abteilung</p>
                  <p class="ro-value">
                    {{ p('department') === 'Sonstige' ? p('department_other') || 'Sonstige' : p('department') }}
                  </p>
                </div>
                <div><p class="ro-label">Kostenstelle</p><p class="ro-value">{{ p('cost_center') }}</p></div>
                <div><p class="ro-label">Niederlassung</p><p class="ro-value">{{ p('location') }}</p></div>
                <div><p class="ro-label">Bundesland</p><p class="ro-value">{{ p('federal_state') }}</p></div>
                <div><p class="ro-label">Firma lt. Arbeitsvertrag</p><p class="ro-value">{{ p('contract_company') }}</p></div>
              </div>
            </div>

            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Beziehungen</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Vorgesetzter (HR)</p><p class="ro-value">{{ p('supervisor_hr_name') }}</p></div>
                <div><p class="ro-label">Ansprechpartner</p><p class="ro-value">{{ p('contact_person_name') }}</p></div>
              </div>
            </div>

            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Timebutler</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Urlaubsanspruch pro Jahr</p><p class="ro-value">{{ tb('vacation_year') }}</p></div>
                <div><p class="ro-label">Urlaub freigeben</p><p class="ro-value">{{ tb('supervisor_name') }}</p></div>
              </div>
            </div>

            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Fuhrpark</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Dienstwagen</p><p class="ro-value">{{ f('car') }}</p></div>
                <template v-if="f('car') === 'Ja'">
                  <div><p class="ro-label">Fahrzeuggruppe</p><p class="ro-value">{{ f('car_class') }}</p></div>
                  <div><p class="ro-label">Benötigt ab</p><p class="ro-value">{{ f('car_from') }}</p></div>
                </template>
              </div>
            </div>
          </div>

          <!-- IT Systemdaten -->
          <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                      rounded-2xl shadow-sm p-6 space-y-6">
            <h2 class="text-base font-semibold text-[#3EAAB8]">IT / Systemdaten</h2>

            <!-- Firma -->
            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Firma (Signatur / Webseite)</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Firma</p><p class="ro-value">{{ it('appearance_company') }}</p></div>
              </div>
            </div>

            <!-- E-Mail-Signatur -->
            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">E-Mail-Signatur</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Titel (Signatur)</p><p class="ro-value">{{ sig('title') }}</p></div>
                <div><p class="ro-label">Straße</p><p class="ro-value">{{ sig('street') }}</p></div>
                <div><p class="ro-label">Postleitzahl</p><p class="ro-value">{{ sig('zip') }}</p></div>
                <div><p class="ro-label">Ort</p><p class="ro-value">{{ sig('city') }}</p></div>
              </div>
            </div>

            <!-- Software -->
            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Software</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><p class="ro-label">Ausgewählte Software</p><p class="ro-value">{{ softwareList() }}</p></div>
                <div v-if="sw('datev') && data.description?.it?.software?.datev_rights" class="md:col-span-2">
                  <p class="ro-label">DATEV Rechte</p>
                  <p class="ro-value whitespace-pre-wrap">{{ data.description.it.software.datev_rights }}</p>
                </div>
                <div v-if="data.description?.it?.phone_order?.enabled">
                  <p class="ro-label">Festnetz-Telefonnummer beantragen</p>
                  <p class="ro-value">Ja — {{ data.description?.it?.phone_order?.location || '—' }}</p>
                </div>
                <div class="md:col-span-2" v-if="it('other_systems')">
                  <p class="ro-label">Weitere Software</p>
                  <p class="ro-value whitespace-pre-wrap">{{ it('other_systems') }}</p>
                </div>
              </div>
            </div>

            <!-- Postfächer & Kostenstellen -->
            <div>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-3">Postfächer & Kostenstellen</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p class="ro-label">Infopostfach der Niederlassung</p>
                  <p class="ro-value">{{ data.description?.it?.mailboxes?.info_mailbox ? 'Ja' : 'Nein' }}</p>
                </div>
                <div><p class="ro-label">Zusätzliche Postfächer?</p><p class="ro-value">{{ mb('additional') }}</p></div>
                <div v-if="mb('additional') === 'Ja'" class="md:col-span-2">
                  <p class="ro-label">Postfächer</p>
                  <p class="ro-value whitespace-pre-wrap">{{ mb('notes') }}</p>
                </div>
                <div class="md:col-span-2">
                  <p class="ro-label">Zusätzliche Kostenstellen / Niederlassungen</p>
                  <p class="ro-value whitespace-pre-wrap">{{ it('additional_cost_centers') }}</p>
                </div>
              </div>
            </div>
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
        @department-edit="goToEdit"
      />
    </div>
  </AppLayout>
</template>

<style scoped>
@reference "../../style.css";
.ro-label {
  @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5;
}
.ro-value {
  @apply text-sm text-gray-900 dark:text-white;
}
</style>