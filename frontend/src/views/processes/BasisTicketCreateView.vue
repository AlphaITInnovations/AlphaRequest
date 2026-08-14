<script setup lang="ts">
/**
 * Anlege-Formular des Basis-Tickets – BEWUSST eine eigene, feste Ansicht.
 *
 * Das Basis-Ticket ist der eine Prozess, der immer gleich aussieht („Neues
 * Ticket“). Sein Formular ist deshalb nicht generisch aus der Definition
 * gerendert, sondern exakt das Layout des Alt-Systems: Phasen-Vorschau oben,
 * links das Details-Panel (Fachabteilung, Beobachter, Priorität, Kommentar),
 * rechts Titel und Beschreibung, unten die Aktionsleiste.
 *
 * NUR die Oberfläche ist fest – die Daten bleiben der dynamische Prozess
 * (System-Prozess `basis-ticket`, vom Start selbst gepflegt):
 *   Titel        → Auftrags-Titel (Spalte `title`)
 *   Beschreibung → erster Eintrag in `ticket.eintraege` (der Server stempelt
 *                  Autor:in und Zeitpunkt)
 *   Fachabteilung→ `ticket.fachabteilung` (dorthin schaltet der Auftrag direkt)
 *   Beobachter   → nach dem Anlegen über die Beobachter-API (die Ersteller:in
 *                  trägt der Server automatisch ein)
 *   Kommentar    → nach dem Anlegen als Nachtrag (Verlauf); optional
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { errorCode, errorMessage, issuesFromError } from '@/lib/processErrors'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { BASIS_TICKET_KEY } from '@/lib/basisTicket'
import * as processesApi from '@/api/processes'
import { createTicket } from '@/api/processTickets'
import { addComment, addWatcher, removeWatcher } from '@/api/processEvents'
import type { OptionSources } from '@/types/process'

const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const loading = ref(true)
const submitting = ref(false)
const verfuegbar = ref(true)
const sources = ref<OptionSources>(emptySources())

/** Phasen für „So läuft dieser Auftrag“ – aus der veröffentlichten Definition,
 *  nicht hartcodiert: ändert sich der Ablauf, stimmt die Vorschau weiter. */
const phasen = ref<string[]>([])

// ── Eingaben ──────────────────────────────────────────────────────────────────
const titel = ref('')
const beschreibung = ref('')
const fachabteilung = ref('')
const prioritaet = ref('normal')
const kommentar = ref('')
const feldFehler = ref<Record<string, string>>({})

/** Wire-Werte des Backends (ALLOWED_PRIORITY), Beschriftung wie im Alt-System. */
const PRIORITAETEN = [
  { value: 'low', label: 'Niedrig' },
  { value: 'normal', label: 'Mittel' },
  { value: 'high', label: 'Hoch' },
  { value: 'urgent', label: 'Kritisch' },
]

// ── Beobachter ────────────────────────────────────────────────────────────────
// Die Ersteller:in wird vom Server automatisch eingetragen und steht deshalb
// schon vor dem Anlegen in der Liste. Änderungen (weitere Personen, Entfernen
// der eigenen Beobachtung) werden NACH dem Anlegen über die Beobachter-API
// nachgezogen – beim Anlegen selbst kennt der Server nur die Ersteller:in.
const beobachter = ref<{ id: string; name: string }[]>([])
const beobachterAuswahl = ref('')

const offenePersonen = computed(() => {
  const drin = new Set(beobachter.value.map((w) => w.id))
  return sources.value.users.filter((u) => !drin.has(u.id))
})

function beobachterHinzu() {
  const u = sources.value.users.find((x) => x.id === beobachterAuswahl.value)
  if (u) beobachter.value.push({ id: u.id, name: u.displayName })
  beobachterAuswahl.value = ''
}

function beobachterWeg(id: string) {
  beobachter.value = beobachter.value.filter((w) => w.id !== id)
}

const initial = (name: string) => (name.trim()[0] || '?').toUpperCase()

// ── Laden ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (auth.user?.id) {
    beobachter.value = [{ id: auth.user.id, name: auth.user.displayName || auth.user.id }]
  }
  // Öffentliche Quellen (adminGroups=false): auch Nicht-Admins wählen hier eine
  // Fachabteilung – der Admin-Endpunkt lieferte ihnen eine leere Liste.
  sources.value = await loadOptionSources(false)
  try {
    const row = await processesApi.getPublished(BASIS_TICKET_KEY)
    phasen.value = (row.definition?.phases ?? []).map((p) => p.label || p.key)
  } catch (e) {
    // Der System-Prozess entsteht beim Anwendungsstart von selbst. Fehlt er,
    // ist der Start nicht durchgelaufen – das ist ein Betriebsproblem, kein
    // Bedienfehler, und gehört so benannt.
    verfuegbar.value = errorCode(e) !== 'PROCESS_NOT_FOUND'
    if (verfuegbar.value) showToast(errorMessage(e, 'Basis-Ticket konnte nicht geladen werden'), false)
  } finally {
    loading.value = false
  }
})

// ── Anlegen ───────────────────────────────────────────────────────────────────
function pruefen(): boolean {
  const f: Record<string, string> = {}
  if (!titel.value.trim()) f.titel = 'Bitte einen Titel angeben.'
  if (!beschreibung.value.trim()) f.beschreibung = 'Bitte das Anliegen beschreiben.'
  if (!fachabteilung.value) f.fachabteilung = 'Bitte eine Fachabteilung wählen.'
  feldFehler.value = f
  return Object.keys(f).length === 0
}

async function erstellen() {
  if (!pruefen()) { showToast('Bitte die markierten Felder prüfen', false); return }
  submitting.value = true
  try {
    const t = await createTicket({
      processKey: BASIS_TICKET_KEY,
      title: titel.value.trim(),
      priority: prioritaet.value,
      values: {
        'ticket.fachabteilung': fachabteilung.value,
        'ticket.eintraege': [{ text: beschreibung.value.trim() }],
      },
    })

    // Beobachter und Kommentar NACH dem Anlegen – best-effort: der Auftrag ist
    // angelegt und bei der Fachabteilung; ein Fehlschlag hier darf das nicht
    // mehr rückgängig machen, wird aber gemeldet statt verschluckt.
    const ich = auth.user?.id
    try {
      for (const w of beobachter.value) {
        if (w.id !== ich) await addWatcher(t.id, w.id)
      }
      if (ich && !beobachter.value.some((w) => w.id === ich)) {
        await removeWatcher(t.id, ich)
      }
      if (kommentar.value.trim()) {
        await addComment(t.id, kommentar.value.trim())
      }
    } catch (e) {
      showToast(errorMessage(e, 'Auftrag angelegt, aber Beobachter/Kommentar konnten '
        + 'nicht vollständig übernommen werden'), false)
    }

    showToast('Auftrag angelegt')
    router.push(`/prozess-auftraege/${t.id}`)
  } catch (e) {
    const issues = issuesFromError(e)
    const f: Record<string, string> = {}
    for (const i of issues) {
      if (i.path === 'ticket.fachabteilung') f.fachabteilung = i.message
      else if (i.path === 'ticket.eintraege') f.beschreibung = i.message
      else f.titel = f.titel || i.message
    }
    feldFehler.value = f
    showToast(errorMessage(e, 'Anlegen fehlgeschlagen'), false)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppLayout title="Basis-Ticket">
    <div class="max-w-5xl mx-auto px-4 py-6">
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <div v-else-if="!verfuegbar"
           class="rounded-2xl border border-amber-200 dark:border-amber-500/30
                  bg-amber-50 dark:bg-amber-900/20 px-5 py-4">
        <p class="text-sm text-amber-900 dark:text-amber-200">
          Das Basis-Ticket ist nicht verfügbar. Es wird beim Start der Anwendung
          automatisch eingerichtet – wenn diese Meldung bleibt, ist der letzte
          Start nicht sauber durchgelaufen (Server-Log prüfen).
        </p>
      </div>

      <template v-else>
        <!-- Phasen-Vorschau -->
        <div class="card-section mb-4">
          <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            So läuft dieser Auftrag
          </p>
          <ol class="flex items-center gap-2 flex-wrap">
            <li v-for="(p, i) in phasen" :key="p" class="flex items-center gap-2">
              <span class="flex items-center gap-2">
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold"
                      :class="i === 0 ? 'bg-[#3EAAB8] text-white'
                                      : 'bg-[#3EAAB8]/10 text-[#3EAAB8]'">{{ i + 1 }}</span>
                <span class="text-sm text-gray-700 dark:text-gray-200">{{ p }}</span>
              </span>
              <svg v-if="i < phasen.length - 1" class="w-4 h-4 text-gray-300 dark:text-gray-600"
                   viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5-5 5M6 12h12"/>
              </svg>
            </li>
          </ol>
        </div>

        <div class="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr] items-start">
          <!-- Details (links) -->
          <div class="card-section space-y-5">
            <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100">Details</h3>

            <div>
              <label class="block text-sm text-gray-700 dark:text-gray-200 mb-1.5">
                Zuständige Fachabteilung <span class="text-red-500">*</span>
              </label>
              <select v-model="fachabteilung" class="afi w-full"
                      :class="feldFehler.fachabteilung ? 'border-red-400' : ''">
                <option value="">Fachabteilung auswählen…</option>
                <option v-for="g in sources.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
              </select>
              <p v-if="feldFehler.fachabteilung" class="text-xs text-red-500 mt-1">
                {{ feldFehler.fachabteilung }}
              </p>
            </div>

            <div>
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Beobachter
              </p>
              <ul class="space-y-1.5 mb-2">
                <li v-for="w in beobachter" :key="w.id"
                    class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
                  <span class="w-6 h-6 rounded-full bg-[#3EAAB8]/15 text-[#3EAAB8]
                               flex items-center justify-center text-xs font-semibold">
                    {{ initial(w.name) }}
                  </span>
                  <span class="truncate">{{ w.name }}</span>
                  <button @click="beobachterWeg(w.id)"
                          class="ml-auto text-gray-300 hover:text-red-500 transition"
                          :aria-label="`${w.name} entfernen`">✕</button>
                </li>
              </ul>
              <select v-model="beobachterAuswahl" @change="beobachterHinzu" class="afi w-full">
                <option value="">Beobachter hinzufügen…</option>
                <option v-for="u in offenePersonen" :key="u.id" :value="u.id">
                  {{ u.displayName }}
                </option>
              </select>
            </div>

            <div>
              <label class="block text-sm text-gray-700 dark:text-gray-200 mb-1.5">Priorität</label>
              <select v-model="prioritaet" class="afi w-full">
                <option v-for="p in PRIORITAETEN" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>

            <div>
              <label class="block text-sm text-gray-700 dark:text-gray-200 mb-1.5">Kommentar</label>
              <textarea v-model="kommentar" rows="4" class="afi w-full resize-none"
                        placeholder="Optionaler Kommentar…" />
            </div>
          </div>

          <!-- Anliegen (rechts) -->
          <div class="space-y-4">
            <div class="card-section">
              <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">
                Titel <span class="text-red-500">*</span>
              </label>
              <input v-model="titel" maxlength="255" class="afi w-full"
                     :class="feldFehler.titel ? 'border-red-400' : ''"
                     placeholder="Kurze Beschreibung des Anliegens…" />
              <p v-if="feldFehler.titel" class="text-xs text-red-500 mt-1">{{ feldFehler.titel }}</p>
            </div>

            <div class="card-section">
              <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">
                Beschreibung <span class="text-red-500">*</span>
              </label>
              <textarea v-model="beschreibung" rows="6" class="afi w-full resize-y"
                        :class="feldFehler.beschreibung ? 'border-red-400' : ''"
                        placeholder="Beschreibe dein Anliegen ausführlich…" />
              <p v-if="feldFehler.beschreibung" class="text-xs text-red-500 mt-1">
                {{ feldFehler.beschreibung }}
              </p>
            </div>
          </div>
        </div>

        <!-- Aktionsleiste -->
        <div class="card-section mt-4 flex items-center justify-end gap-2">
          <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
          <button @click="erstellen" :disabled="submitting"
                  class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                         disabled:opacity-40 transition">
            {{ submitting ? 'Wird angelegt…' : 'Auftrag erstellen' }}
          </button>
        </div>
      </template>
    </div>
  </AppLayout>
</template>
