<script setup lang="ts">
interface HistoryActor {
  id: string | null
  name: string
  type: string
}

interface HistoryEvent {
  timestamp: string
  actor: HistoryActor
  action: string
  details: Record<string, any>
}

defineProps<{ history: HistoryEvent[] }>()

// ── Labels & Icons ────────────────────────────────────────────────────────────

const ACTION_META: Record<string, { label: string; icon: string; color: string }> = {
  ticket_created:           { label: 'Ticket erstellt',              icon: '📝', color: 'bg-[#3EAAB8]' },
  ticket_updated:           { label: 'Ticket bearbeitet',            icon: '✏️', color: 'bg-amber-400' },
  ticket_submitted:         { label: 'An Fachabteilungen übergeben', icon: '📤', color: 'bg-blue-500' },
  ticket_archived:          { label: 'Ticket archiviert',            icon: '📦', color: 'bg-gray-400' },
  ticket_archived_manual:   { label: 'Manuell archiviert',           icon: '📦', color: 'bg-gray-400' },
  status_changed:           { label: 'Status geändert',              icon: '🔄', color: 'bg-purple-500' },
  department_status_changed:{ label: 'Fachabteilung',                icon: '🏢', color: 'bg-teal-500' },
  description_changed:      { label: 'Formular bearbeitet',          icon: '📋', color: 'bg-amber-400' },
}

const STATUS_LABEL: Record<string, string> = {
  in_request: 'Zu bearbeiten', in_progress: 'In Bearbeitung',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}

const FIELD_LABEL: Record<string, string> = {
  priority:    'Priorität',
  comment:     'Kommentar',
  description: 'Formular',
  assignee:    'Zuständig',
  accountable: 'Verantwortlich',
}

const DEPT_STATUS_LABEL: Record<string, string> = {
  done: 'Erledigt', rejected: 'Abgelehnt', skipped: 'Übersprungen',
  open: 'Offen', in_progress: 'In Bearbeitung',
}

const DEPT_STATUS_CLASS: Record<string, string> = {
  done:        'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  skipped:     'bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400',
  open:        'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(ts: string) {
  if (!ts) return '—'
  const s = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : ts + 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function getMeta(action: string) {
  return ACTION_META[action] ?? { label: action, icon: '🔹', color: 'bg-gray-400' }
}

// Nur geänderte Keys aus einem description-Snapshot-Diff extrahieren
function descriptionDiff(old: Record<string, any>, next: Record<string, any>): { key: string; section: string; oldVal: any; newVal: any }[] {
  const result: { key: string; section: string; oldVal: any; newVal: any }[] = []
  for (const section of Object.keys(next)) {
    const oldSec = old?.[section] ?? {}
    const newSec = next[section] ?? {}
    for (const key of Object.keys(newSec)) {
      if (JSON.stringify(oldSec[key]) !== JSON.stringify(newSec[key])) {
        result.push({ key, section, oldVal: oldSec[key] ?? '—', newVal: newSec[key] })
      }
    }
  }
  return result
}

function formatVal(v: any): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  return String(v)
}

function labelize(s: string) {
  return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
</script>

<template>
  <div>
    <h2 class="text-base font-semibold text-gray-900 dark:text-white mb-5">Verlauf</h2>

    <p v-if="history.length === 0" class="text-sm text-gray-400 italic">
      Kein Verlauf vorhanden.
    </p>

    <ol v-else class="relative border-l border-gray-200 dark:border-white/[0.09] pl-5 space-y-6">
      <li v-for="e in [...history].reverse()" :key="e.timestamp" class="relative">

        <!-- Dot -->
        <span class="absolute -left-[17px] top-1.5 w-3 h-3 rounded-full ring-2 ring-white dark:ring-[#212B3A]"
              :class="getMeta(e.action).color" />

        <div class="bg-gray-50 dark:bg-[#1A2130] rounded-xl p-3.5 space-y-2">

          <!-- Header -->
          <div class="flex items-start justify-between gap-3">
            <p class="text-sm font-semibold text-gray-900 dark:text-white">
              {{ getMeta(e.action).icon }}&nbsp;{{ getMeta(e.action).label }}
            </p>
            <div class="text-right flex-shrink-0">
              <p class="text-xs font-medium text-gray-700 dark:text-gray-300">{{ e.actor.name }}</p>
              <p class="text-xs text-gray-400">{{ formatDate(e.timestamp) }}</p>
            </div>
          </div>

          <!-- ticket_created: priority + type -->
          <template v-if="e.action === 'ticket_created'">
            <div class="flex gap-2 flex-wrap">
              <span class="text-xs px-2 py-0.5 rounded-full bg-[#3EAAB8]/15 text-[#3EAAB8] font-medium">
                {{ labelize(e.details.ticket_type ?? '') }}
              </span>
              <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300 font-medium capitalize">
                Priorität: {{ e.details.priority ?? '—' }}
              </span>
            </div>
          </template>

          <!-- ticket_updated: changes pro Feld -->
          <template v-if="e.action === 'ticket_updated' && e.details?.changes">

            <!-- description snapshot diff -->
            <template v-if="e.details.changes.description">
              <div class="space-y-1.5">
                <p class="text-xs text-gray-400 font-medium uppercase tracking-wider">Formular-Änderungen</p>
                <div v-for="diff in descriptionDiff(e.details.changes.description.old, e.details.changes.description.new)"
                     :key="diff.section + diff.key"
                     class="grid grid-cols-[auto_1fr_1fr] gap-x-3 gap-y-0.5 text-xs items-baseline">
                  <span class="text-gray-400">{{ labelize(diff.key) }}</span>
                  <span class="line-through text-red-400 dark:text-red-400 truncate">{{ formatVal(diff.oldVal) }}</span>
                  <span class="text-green-600 dark:text-green-400 font-medium truncate">{{ formatVal(diff.newVal) }}</span>
                </div>
              </div>
            </template>

            <!-- einfache Felder (priority, comment, assignee, accountable) -->
            <template v-for="(change, field) in e.details.changes" :key="field">
              <div v-if="field !== 'description'"
                   class="grid grid-cols-[100px_1fr] gap-x-3 text-xs items-baseline">
                <span class="text-gray-400">{{ FIELD_LABEL[field] ?? labelize(String(field)) }}</span>
                <span>
                  <span class="line-through text-red-400 dark:text-red-400 mr-1.5">{{ formatVal(change.old) }}</span>
                  <span class="text-green-600 dark:text-green-400 font-medium">{{ formatVal(change.new) }}</span>
                </span>
              </div>
            </template>

          </template>

          <!-- ticket_submitted -->
          <template v-if="e.action === 'ticket_submitted'">
            <p class="text-xs text-gray-400">Status → <span class="font-medium text-[#3EAAB8]">Zu bearbeiten</span></p>
          </template>

          <!-- status_changed -->
          <template v-if="e.action === 'status_changed' && e.details?.field === 'status'">
            <div class="flex items-center gap-2 text-xs">
              <span class="text-gray-400 line-through">{{ STATUS_LABEL[e.details.old_value] ?? e.details.old_value }}</span>
              <span class="text-gray-400">→</span>
              <span class="font-medium text-gray-800 dark:text-gray-200">{{ STATUS_LABEL[e.details.new_value] ?? e.details.new_value }}</span>
            </div>
          </template>

          <!-- department_status_changed -->
          <template v-if="e.action === 'department_status_changed'">
            <div class="flex items-center gap-2 text-xs">
              <span class="font-medium text-gray-700 dark:text-gray-300">{{ e.details?.department_name ?? e.details?.department_id }}</span>
              <span class="px-2 py-0.5 rounded-full font-medium"
                    :class="DEPT_STATUS_CLASS[e.details?.new_value] ?? 'bg-gray-100 text-gray-500'">
                {{ DEPT_STATUS_LABEL[e.details?.new_value] ?? e.details?.new_value }}
              </span>
            </div>
          </template>

          <!-- System-Actor Badge -->
          <div v-if="e.actor.type === 'system'"
               class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full
                      bg-gray-100 dark:bg-white/10 text-gray-400">
            ⚙️ System
          </div>

        </div>
      </li>
    </ol>
  </div>
</template>