<script setup lang="ts">
/**
 * Anlege-Formular des Basis-Tickets – BEWUSST eine eigene, feste Ansicht.
 *
 * Das Basis-Ticket ist der eine Prozess, der immer gleich aussieht („Neues
 * Ticket“). Sein Formular ist deshalb nicht generisch aus der Definition
 * gerendert, sondern das Layout des Alt-Systems: links das Details-Panel
 * (Fachabteilung, Beobachter), rechts Titel und Beschreibung, unten die
 * Aktionsleiste. BEWUSST ohne Phasen-Vorschau – die zwei internen Phasen des
 * Basis-Tickets sagen nichts aus (dynamische Prozesse behalten ihre).
 *
 * PRIORITÄT UND KOMMENTAR sind hier bewusst NICHT setzbar: Backend und Datenbank
 * kennen beides weiterhin (PATCH `priority`, Nachtrags-Endpunkt), aber solange
 * unklar ist, wie sie sinnvoll eingesetzt werden, bietet die Oberfläche sie
 * nirgends an.
 *
 * NUR die Oberfläche ist fest – die Daten bleiben der dynamische System-Prozess:
 *   Titel        → Auftrags-Titel (Spalte `title`)
 *   Beschreibung → erster Eintrag in `ticket.eintraege` (der Server stempelt
 *                  Autor:in und Zeitpunkt)
 *   Fachabteilung→ `ticket.fachabteilung` (dorthin schaltet der Auftrag direkt)
 *   Beobachter   → nach dem Anlegen über die Beobachter-API (die Ersteller:in
 *                  trägt der Server automatisch ein)
 *   Anhänge      → nach dem Anlegen über die Anhang-API (ein Anhang braucht die
 *                  Ticket-ID; die Ersteller:in darf laut Server nachreichen)
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import UserSelect from '@/components/UserSelect.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'
import { errorCode, errorMessage, issuesFromError } from '@/lib/processErrors'
import { BASIS_TICKET_KEY } from '@/lib/basisTicket'
import * as processesApi from '@/api/processes'
import { createTicket } from '@/api/processTickets'
import { addWatcher, removeWatcher } from '@/api/processEvents'
import { uploadAttachment } from '@/api/processAttachments'

const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const loading = ref(true)
const submitting = ref(false)
const verfuegbar = ref(true)

// ── Eingaben ──────────────────────────────────────────────────────────────────
const titel = ref('')
const beschreibung = ref('')
const fachabteilung = ref<{ id: string; name: string } | null>(null)
const feldFehler = ref<Record<string, string>>({})

// ── Beobachter ────────────────────────────────────────────────────────────────
// Die Ersteller:in wird vom Server automatisch eingetragen und steht deshalb
// schon vor dem Anlegen in der Liste. Änderungen werden NACH dem Anlegen über
// die Beobachter-API nachgezogen.
const beobachter = ref<{ id: string; name: string }[]>([])
/** Erzwingt nach jeder Auswahl einen frischen Picker (leert dessen Suchfeld). */
const pickerKey = ref(0)

function beobachterHinzu(sel: { id: string; name: string } | null) {
  if (sel && !beobachter.value.some((w) => w.id === sel.id)) {
    beobachter.value.push(sel)
  }
  pickerKey.value++
}

function beobachterWeg(id: string) {
  beobachter.value = beobachter.value.filter((w) => w.id !== id)
}

const initial = (name: string) => (name.trim()[0] || '?').toUpperCase()

// ── Anhänge ───────────────────────────────────────────────────────────────────
// Dateien werden bis zum Anlegen nur GESAMMELT: ein Anhang hängt an einer
// Ticket-ID, und die gibt es erst nach dem Erstellen.
const dateien = ref<File[]>([])
const dateiInput = ref<HTMLInputElement | null>(null)

function dateienGewaehlt(ev: Event) {
  const input = ev.target as HTMLInputElement
  for (const f of Array.from(input.files ?? [])) {
    if (!dateien.value.some((d) => d.name === f.name && d.size === f.size)) {
      dateien.value.push(f)
    }
  }
  // Input leeren: sonst löst dieselbe Datei beim zweiten Mal kein Event aus.
  input.value = ''
}

function dateiWeg(index: number) {
  dateien.value = dateien.value.filter((_, i) => i !== index)
}

const groesse = (b: number) => (b < 1024 * 1024
  ? `${Math.max(1, Math.round(b / 1024))} KB`
  : `${(b / (1024 * 1024)).toFixed(1)} MB`)

// ── Laden ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (auth.user?.id) {
    beobachter.value = [{ id: auth.user.id, name: auth.user.displayName || auth.user.id }]
  }
  try {
    // Nur die Verfügbarkeit prüfen – gerendert wird aus der Definition nichts.
    await processesApi.getPublished(BASIS_TICKET_KEY)
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
      values: {
        'ticket.fachabteilung': fachabteilung.value!.id,
        'ticket.eintraege': [{ text: beschreibung.value.trim() }],
      },
    })

    // Beobachter NACH dem Anlegen – best-effort: der Auftrag ist angelegt und bei
    // der Fachabteilung; ein Fehlschlag hier darf das nicht mehr rückgängig
    // machen, wird aber gemeldet statt verschluckt.
    const ich = auth.user?.id
    try {
      for (const w of beobachter.value) {
        if (w.id !== ich) await addWatcher(t.id, w.id)
      }
      if (ich && !beobachter.value.some((w) => w.id === ich)) {
        await removeWatcher(t.id, ich)
      }
    } catch (e) {
      showToast(errorMessage(e, 'Auftrag angelegt, aber die Beobachter konnten '
        + 'nicht vollständig übernommen werden'), false)
    }

    // Anhänge NACH dem Anlegen – gleiche best-effort-Logik: melden, nicht
    // verschlucken (die Datei kann in der Ticket-Ansicht nachgereicht werden).
    const fehlgeschlagen: string[] = []
    for (const f of dateien.value) {
      try {
        await uploadAttachment(t.id, f)
      } catch {
        fehlgeschlagen.push(f.name)
      }
    }
    if (fehlgeschlagen.length) {
      showToast('Auftrag angelegt, aber diese Dateien konnten nicht hochgeladen '
        + `werden: ${fehlgeschlagen.join(', ')}`, false)
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
        <div class="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr] items-start">
          <!-- Details (links) -->
          <div class="card-section space-y-5">
            <h3 class="text-base font-semibold text-gray-800 dark:text-gray-100">Details</h3>

            <div>
              <UserSelect v-model="fachabteilung"
                          label="Zuständige Fachabteilung *"
                          placeholder="Fachabteilung auswählen…"
                          :show-groups="true" :show-users="false" />
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
              <UserSelect :key="pickerKey" :model-value="null" label=""
                          placeholder="Beobachter hinzufügen…"
                          @update:model-value="beobachterHinzu" />
            </div>
          </div>

          <!-- Anliegen (rechts) -->
          <div class="space-y-4">
            <div class="card-section">
              <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">
                Titel <span class="text-red-500">*</span>
              </label>
              <input v-model="titel" maxlength="255" class="afi w-full"
                     :class="feldFehler.titel ? '!border-red-400' : ''"
                     placeholder="Kurze Beschreibung des Anliegens…" />
              <p v-if="feldFehler.titel" class="text-xs text-red-500 mt-1">{{ feldFehler.titel }}</p>
            </div>

            <div class="card-section">
              <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">
                Beschreibung <span class="text-red-500">*</span>
              </label>
              <textarea v-model="beschreibung" rows="6" class="afi w-full resize-y"
                        :class="feldFehler.beschreibung ? '!border-red-400' : ''"
                        placeholder="Beschreibe dein Anliegen ausführlich…" />
              <p v-if="feldFehler.beschreibung" class="text-xs text-red-500 mt-1">
                {{ feldFehler.beschreibung }}
              </p>
            </div>

            <div class="card-section">
              <label class="block text-sm font-medium text-gray-800 dark:text-gray-100 mb-1.5">
                Anhänge
              </label>
              <ul v-if="dateien.length"
                  class="divide-y divide-gray-100 dark:divide-white/[0.06] rounded-xl
                         border border-gray-200 dark:border-white/10 overflow-hidden mb-2">
                <li v-for="(f, i) in dateien" :key="f.name + f.size"
                    class="flex items-center gap-3 px-3 py-2">
                  <span class="truncate text-sm text-gray-700 dark:text-gray-200"
                        :title="f.name">{{ f.name }}</span>
                  <span class="text-xs text-gray-400 whitespace-nowrap">{{ groesse(f.size) }}</span>
                  <button type="button" @click="dateiWeg(i)"
                          class="ml-auto text-gray-300 hover:text-red-500 transition"
                          :aria-label="`${f.name} entfernen`">✕</button>
                </li>
              </ul>
              <input ref="dateiInput" type="file" multiple class="hidden"
                     @change="dateienGewaehlt" />
              <button type="button" class="btn-secondary text-sm" @click="dateiInput?.click()">
                Datei hinzufügen
              </button>
              <p class="text-xs text-gray-400 mt-2">
                Die Dateien werden beim Erstellen des Auftrags hochgeladen.
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

