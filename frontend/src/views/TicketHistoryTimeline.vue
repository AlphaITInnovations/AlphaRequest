<script setup lang="ts">
import {
  labelize, fieldLabel, formatVal, isText, commentVerb, descriptionDiff,
} from '@/utils/historyDiff'

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
  ticket_rejected:          { label: 'Abgelehnt',                    icon: '⛔', color: 'bg-red-500' },
  phase_advanced:           { label: 'Phase abgeschlossen',          icon: '➡️', color: 'bg-blue-500' },
  freigabe_approved_mail:   { label: 'Freigegeben (per Mail)',       icon: '✅', color: 'bg-green-500' },
  freigabe_rejected_mail:   { label: 'Abgelehnt (per Mail)',         icon: '⛔', color: 'bg-red-500' },
  nachtrag_added:           { label: 'Nachtrag',                     icon: '📝', color: 'bg-indigo-500' },
  responsibility_overridden:{ label: 'Zuständigkeit (Admin)',        icon: '🛠️', color: 'bg-orange-500' },
  lock_released:            { label: 'Sperre aufgehoben (Admin)',    icon: '🔓', color: 'bg-orange-500' },
  status_changed:           { label: 'Status geändert',              icon: '🔄', color: 'bg-purple-500' },
  department_status_changed:{ label: 'Fachabteilung',                icon: '🏢', color: 'bg-teal-500' },
  description_changed:      { label: 'Formular bearbeitet',          icon: '📋', color: 'bg-amber-400' },
  admin_raw_edited:         { label: 'Notfall-Bearbeitung (Admin)',  icon: '🧬', color: 'bg-orange-500' },
}

const STATUS_LABEL: Record<string, string> = {
  in_request: 'Zu bearbeiten', in_progress: 'In Bearbeitung',
  archived: 'Archiviert', rejected: 'Abgelehnt',
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

// Verlaufs-Events mit gebündelten Feld-Änderungen (gleiche Diff-Darstellung).
function isFieldEdit(action: string): boolean {
  return action === 'ticket_updated' || action === 'admin_raw_edited'
}

// Enthält ein Verlaufs-Event eine Kommentar-Änderung? (für den Highlight-Rahmen)
function hasComment(e: HistoryEvent): boolean {
  if (!isFieldEdit(e.action)) return false
  const c = e.details?.changes?.comment
  return !!c && (isText(c.old) || isText(c.new))
}

// Reine Kommentar-Änderung (keine weiteren Felder) → eigener Header „💬 Kommentar"
function isCommentOnly(e: HistoryEvent): boolean {
  if (!hasComment(e)) return false
  return Object.keys(e.details?.changes ?? {}).length === 1
}

// Gibt es einfache Feldänderungen außer description/comment? (Diff-Block nur dann zeigen)
function hasSimpleFields(e: HistoryEvent): boolean {
  return Object.keys(e.details?.changes ?? {}).some(k => k !== 'description' && k !== 'comment')
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

        <div class="bg-gray-50 dark:bg-[#1A2130] rounded-xl p-3.5 space-y-2"
             :class="hasComment(e) ? 'ring-1 ring-amber-300/70 dark:ring-amber-400/25' : ''">

          <!-- Header -->
          <div class="flex items-start justify-between gap-3">
            <p class="text-sm font-semibold text-gray-900 dark:text-white">
              <template v-if="isCommentOnly(e)">💬&nbsp;Kommentar</template>
              <template v-else>{{ getMeta(e.action).icon }}&nbsp;{{ getMeta(e.action).label }}</template>
            </p>
            <div class="text-right flex-shrink-0">
              <p class="text-xs font-medium text-gray-700 dark:text-gray-300">{{ e.actor.name }}</p>
              <p class="text-xs text-gray-400">{{ formatDate(e.timestamp) }}</p>
            </div>
          </div>

          <!-- ticket_created -->
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

          <!-- ticket_updated / admin_raw_edited: gebündelte Feld-Änderungen -->
          <template v-if="isFieldEdit(e.action) && e.details?.changes">

            <!-- Kommentar – hervorgehoben (Highlight) -->
            <div v-if="e.details.changes.comment"
                 class="rounded-xl border border-amber-200/80 dark:border-amber-400/20
                        border-l-4 border-l-amber-400 dark:border-l-amber-400/80
                        bg-amber-50 dark:bg-amber-400/[0.07] pl-3.5 pr-3 py-2.5">
              <div class="flex items-center gap-1.5 mb-1">
                <span class="text-sm leading-none">💬</span>
                <span class="text-[11px] font-bold uppercase tracking-wider
                             text-amber-700 dark:text-amber-300">
                  {{ commentVerb(e.details.changes.comment) }}
                </span>
              </div>
              <p v-if="isText(e.details.changes.comment.new)"
                 class="text-sm text-gray-800 dark:text-amber-50/90 whitespace-pre-wrap leading-relaxed">
                {{ e.details.changes.comment.new }}
              </p>
              <p v-if="isText(e.details.changes.comment.old)"
                 class="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
                Vorher:
                <span class="line-through">{{ e.details.changes.comment.old }}</span>
              </p>
            </div>

            <!-- description snapshot diff (rekursiv geflattened) -->
            <template v-if="e.details.changes.description">
              <div class="space-y-2">
                <p class="text-xs text-gray-400 font-medium uppercase tracking-wider">Formular-Änderungen</p>
                <template v-if="descriptionDiff(e.details.changes.description.old, e.details.changes.description.new).length > 0">
                  <div v-for="diff in descriptionDiff(e.details.changes.description.old, e.details.changes.description.new)"
                       :key="diff.key"
                       class="text-xs rounded-lg bg-white dark:bg-white/[0.03]
                              border border-gray-100 dark:border-white/[0.06] px-2.5 py-1.5">
                    <p class="text-gray-500 dark:text-gray-400 font-medium mb-0.5">{{ diff.label }}</p>
                    <div class="leading-relaxed break-words">
                      <span class="line-through text-red-400">{{ formatVal(diff.oldVal) }}</span>
                      <span class="mx-1 text-gray-400">→</span>
                      <span class="text-green-600 dark:text-green-400 font-medium">{{ formatVal(diff.newVal) }}</span>
                    </div>
                  </div>
                </template>
                <p v-else class="text-xs text-gray-400 italic">Keine sichtbaren Änderungen</p>
              </div>
            </template>

            <!-- einfache Felder (priority, assignee, accountable) – Kommentar oben separat -->
            <div v-if="hasSimpleFields(e)" class="space-y-2 mt-2">
              <template v-for="(change, field) in e.details.changes" :key="field">
                <div v-if="field !== 'description' && field !== 'comment'"
                     class="text-xs rounded-lg bg-white dark:bg-white/[0.03]
                            border border-gray-100 dark:border-white/[0.06] px-2.5 py-1.5">
                  <p class="text-gray-500 dark:text-gray-400 font-medium mb-0.5">{{ fieldLabel(String(field)) }}</p>
                  <div class="leading-relaxed break-words">
                    <span class="line-through text-red-400">{{ formatVal(change.old) }}</span>
                    <span class="mx-1 text-gray-400">→</span>
                    <span class="text-green-600 dark:text-green-400 font-medium">{{ formatVal(change.new) }}</span>
                  </div>
                </div>
              </template>
            </div>

          </template>

          <!-- ticket_submitted -->
          <template v-if="e.action === 'ticket_submitted'">
            <p class="text-xs text-gray-400">
              Status →
              <span class="font-medium text-[#3EAAB8]">
                {{ STATUS_LABEL[e.details?.status_new] ?? 'Zu bearbeiten' }}
              </span>
            </p>
          </template>

          <!-- ticket_rejected: Grund anzeigen -->
          <template v-if="e.action === 'ticket_rejected' && e.details?.message">
            <p class="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
              Grund: {{ e.details.message }}
            </p>
          </template>

          <!-- nachtrag_added: Text anzeigen -->
          <template v-if="e.action === 'nachtrag_added' && e.details?.text">
            <p class="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{{ e.details.text }}</p>
          </template>

          <!-- responsibility_overridden: alt → neu (+ Phase) -->
          <template v-if="e.action === 'responsibility_overridden'">
            <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-xs">
              <span class="text-gray-400 line-through">{{ e.details?.old || '—' }}</span>
              <span class="text-gray-400">→</span>
              <span class="font-medium text-gray-800 dark:text-gray-200">{{ e.details?.new }}</span>
              <span v-if="e.details?.phase_label" class="text-gray-400">· {{ e.details.phase_label }}</span>
            </div>
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