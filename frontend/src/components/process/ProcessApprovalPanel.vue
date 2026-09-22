<script setup lang="ts">
/**
 * Freigabe-Entscheidung direkt im Web (Bearbeiten-Ansicht einer Freigabe-Phase).
 *
 * Der authentifizierte Zwilling der JA/NEIN-Mail: die zuständige Stelle (oder ein
 * Admin) genehmigt oder lehnt hier ab, ohne den Mail-Link zu brauchen. Der Server
 * (`POST :decide`) geht denselben Weg wie der Link – Entscheidung festschreiben,
 * protokollieren, dann Wirkung (Weiterschalten bzw. `onReject`: ablehnen oder
 * Rücksprung). Diese Fläche steht GANZ OBEN in der Bearbeiten-Ansicht; darunter
 * zeigt die Detailansicht alle Angaben schreibgeschützt.
 */
import { computed, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import { errorMessage } from '@/lib/processErrors'
import { decideApproval } from '@/api/processTickets'
import type { PhaseDef, ProcessTicketOut } from '@/types/process'

const props = defineProps<{ ticket: ProcessTicketOut; phase: PhaseDef }>()
const emit = defineEmits<{ reload: []; error: [message: string] }>()

const { showToast } = useToast()

const spec = computed(() => props.phase.approval)
/** Eine Ablehnung springt zur Nachbesserung zurück (onReject = back_to:<phase>),
 *  statt den Auftrag endgültig abzulehnen – dann heißt der rote Knopf anders. */
const istRuecksprung = computed(() => (spec.value?.onReject ?? '').startsWith('back_to:'))

const busy = ref(false)
const showReject = ref(false)
const reason = ref('')

async function genehmigen() {
  busy.value = true
  try {
    await decideApproval(props.ticket.id, 'approve')
    showToast('Freigabe erteilt')
    emit('reload')
  } catch (e) {
    emit('error', errorMessage(e, 'Genehmigen fehlgeschlagen'))
  } finally { busy.value = false }
}

async function ablehnen() {
  // Der Server verlangt die Begründung, wenn requireReason gesetzt ist (422). Wir
  // fangen es hier schon ab, damit der Fehler nicht erst nach dem Klick kommt.
  if (spec.value?.requireReason && !reason.value.trim()) {
    showToast('Bitte eine Begründung angeben', false); return
  }
  busy.value = true
  try {
    await decideApproval(props.ticket.id, 'reject', reason.value.trim())
    showToast(istRuecksprung.value ? 'Zur Nachbesserung zurückgegeben' : 'Freigabe abgelehnt')
    emit('reload')
  } catch (e) {
    emit('error', errorMessage(e, 'Ablehnen fehlgeschlagen'))
  } finally { busy.value = false }
}
</script>

<template>
  <div class="rounded-2xl border border-[#3EAAB8]/50 bg-[#3EAAB8]/[0.07] shadow-sm p-5 space-y-3">
    <div class="flex items-center gap-2">
      <span class="text-lg leading-none">📋</span>
      <h2 class="font-semibold text-gray-900 dark:text-white">Freigabe erforderlich</h2>
    </div>
    <p class="text-sm text-gray-700 dark:text-gray-200">
      {{ spec?.question || 'Möchten Sie diesen Auftrag freigeben?' }}
    </p>

    <!-- Zwei Wege: genehmigen (grün) oder ablehnen (rot; klappt das Begründungs-
         feld auf). Beide lösen serverseitig denselben Weg aus wie der Mail-Link. -->
    <div v-if="!showReject" class="flex flex-wrap gap-2">
      <button type="button" @click="genehmigen" :disabled="busy"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium
                     bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50 transition">
        ✅ {{ spec?.approveLabel || 'Genehmigen' }}
      </button>
      <button type="button" @click="showReject = true" :disabled="busy"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium
                     border border-red-300 dark:border-red-500/40 text-red-600 dark:text-red-300
                     hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition">
        {{ istRuecksprung ? '↩️ Zurück zur Nachbesserung' : ('🚫 ' + (spec?.rejectLabel || 'Ablehnen')) }}
      </button>
    </div>

    <!-- Ablehnen: Begründung erfassen (Pflicht, wenn der Prozess sie verlangt). -->
    <div v-else class="space-y-2 rounded-xl border border-red-200 dark:border-red-500/30
                       bg-white dark:bg-[#212B3A] p-3">
      <label class="block text-xs font-medium text-gray-600 dark:text-gray-300">
        Begründung<span v-if="spec?.requireReason" class="text-red-500"> *</span>
        <span v-else class="text-gray-400"> (optional)</span>
      </label>
      <textarea v-model="reason" rows="3" maxlength="5000" class="afi w-full resize-y"
                :placeholder="istRuecksprung ? 'Was ist nachzubessern?' : 'Warum wird abgelehnt?'" />
      <div class="flex justify-end gap-2">
        <button type="button" @click="showReject = false; reason = ''"
                class="btn-secondary text-sm" :disabled="busy">Abbrechen</button>
        <button type="button" @click="ablehnen" :disabled="busy"
                class="px-4 py-2 rounded-xl text-sm font-medium text-white
                       bg-red-600 hover:bg-red-700 disabled:opacity-50 transition">
          {{ busy ? 'Wird gesendet…' : (istRuecksprung ? 'Zurückgeben' : 'Ablehnen') }}
        </button>
      </div>
    </div>
  </div>
</template>
