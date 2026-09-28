<script setup lang="ts">
/**
 * Modal zum Importieren einer Prozess-Definition (Datei oder eingefügtes JSON).
 *
 * Der Ziel-Schlüssel wird IMMER bestätigt und nie still aus dem JSON
 * übernommen: Das Backend legt unter `targetKey` an, und ein versehentlich
 * mitgeschleppter Fremd-Schlüssel würde sonst unbemerkt einen anderen Prozess
 * betreffen.
 *
 * Fremde Fachabteilungs-Referenzen (Platzhalter aus den Vorlagen, IDs aus
 * anderen Installationen) werden VOR dem Import per Dropdown den hiesigen
 * Fachabteilungen zugeordnet – sonst entstünde ein Entwurf voller
 * „Unbekannte Fachabteilung"-Fehler, die man einzeln reparieren müsste.
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { importProcess } from '@/api/processes'
import { normalizeDefinition } from '@/lib/processNormalize'
import { isValidProcessKey, suggestProcessKey } from '@/lib/processSchema'
import { errorCode, errorMessage, issuesFromError } from '@/lib/processErrors'
import { isSystemReadonlyError } from '@/lib/processSystem'
import { replaceGroupRefs, unknownGroupRefs } from '@/lib/processGroupRefs'
import { loadGroupOptions } from '@/lib/processSources'
import { rememberKey } from '@/components/process/processRegistry'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition, ProcessIssue } from '@/types/process'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  close: []
  imported: [payload: { key: string; version: number }]
}>()

const { showToast } = useToast()

const KEY_RULE = 'Kleinbuchstaben, Ziffern und Bindestriche; beginnt mit Buchstabe oder Ziffer; max. 64 Zeichen.'

const rawText    = ref('')
const fileName   = ref<string | null>(null)
const parseError = ref<string | null>(null)
const parsed     = ref<ProcessDefinition | null>(null)
const targetKey  = ref('')
const keyTouched = ref(false)
const keyError   = ref<string | null>(null)
const issues     = ref<ProcessIssue[]>([])
const submitting = ref(false)

const textArea = ref<HTMLTextAreaElement | null>(null)

// ── Fremde Fachabteilungen zuordnen ──────────────────────────────────────────

/** Dropdown-Wert für „unverändert übernehmen" (nur echte IDs, nie Platzhalter). */
const KEEP = '__unveraendert__'

const gruppen = ref<OptionSources['groups']>([])
const gruppenLaden = ref(false)
/** Nur das JÜNGSTE Öffnen darf `gruppen` schreiben – eine späte Antwort eines
 *  früheren Öffnens (403-Fallback braucht zwei Requests) überschriebe sonst
 *  die frische Liste. */
let ladeGeneration = 0

/** Je fremdem Wert die gewählte Gruppen-ID, '' = noch offen, KEEP = belassen. */
const zuordnung = ref<Record<string, string>>({})

const unbekannte = computed(() =>
  parsed.value && gruppen.value.length ? unknownGroupRefs(parsed.value, gruppen.value) : [])

// BEWUSST keine Vorbelegung: die Gruppen-IDs sind je Umgebung (Dev/Prod)
// verschieden, deshalb muss jede Fachabteilung selbst gewählt werden – der
// Namenstreffer steht im Dropdown nur als Empfehlung. Neue Zeilen starten
// „noch offen" ('' → blockiert den Import); bereits getroffene Auswahl bleibt
// erhalten (beim Nachbessern im Textfeld ist das JSON zwischendurch unparsebar,
// dann ist rows=[] und wir fassen nichts an).
watch(unbekannte, (rows) => {
  if (!rows.length) return
  const next = { ...zuordnung.value }
  for (const r of rows) {
    if (!(r.value in next)) next[r.value] = ''
  }
  zuordnung.value = next
})

/** Jede fremde Referenz MUSS zugeordnet werden (Platzhalter wie fremde ID) –
 *  KEEP zählt als getroffene Wahl. */
const offeneZuordnungen = computed(() =>
  unbekannte.value.filter((r) => !zuordnung.value[r.value]).length)

const gruppenSortiert = computed(() =>
  [...gruppen.value].sort((a, b) => a.name.localeCompare(b.name, 'de')))

const keyValid  = computed(() => isValidProcessKey(targetKey.value))
// Solange die Fachabteilungen laden, ist der Import gesperrt – sonst rutschte
// eine schnell eingefügte Vorlage am Zuordnungs-Schritt vorbei.
const canSubmit = computed(() => !submitting.value && !!parsed.value && keyValid.value
  && !gruppenLaden.value && offeneZuordnungen.value === 0)

/** Warnung, wenn die Definition offensichtlich unvollständig ist. */
const structureHint = computed(() => {
  const d = parsed.value
  if (!d) return null
  if (!d.phases.length) return 'Die Definition enthält keine Phasen – ist das wirklich ein Prozess-Export?'
  if (!d.fields.length) return 'Die Definition enthält keinen Feld-Katalog.'
  return null
})

/**
 * Der Export-Endpunkt liefert `{data: …}`, ältere Ablagen `{definition: …}`,
 * manche Kopien beides verschachtelt – deshalb defensiv auswickeln.
 */
function unwrap(value: any): any {
  let v = value
  for (let i = 0; i < 3; i++) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) break
    if (v.definition && typeof v.definition === 'object') { v = v.definition; continue }
    if (v.data && typeof v.data === 'object') { v = v.data; continue }
    break
  }
  return v
}

watch(rawText, (text) => {
  issues.value = []
  keyError.value = null
  if (!text.trim()) {
    parsed.value = null
    parseError.value = null
    return
  }
  let obj: any
  try {
    obj = JSON.parse(text)
  } catch (e: any) {
    parsed.value = null
    parseError.value = `Kein gültiges JSON: ${e?.message || 'Datei konnte nicht gelesen werden'}`
    return
  }
  const inner = unwrap(obj)
  if (!inner || typeof inner !== 'object' || Array.isArray(inner)) {
    parsed.value = null
    parseError.value = 'Der Inhalt enthält keine Prozess-Definition.'
    return
  }
  parseError.value = null
  const defn = normalizeDefinition(inner)
  parsed.value = defn
  if (!keyTouched.value) targetKey.value = defn.key || suggestProcessKey(defn.name)
})

watch(targetKey, () => { keyError.value = null })

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  // Wert leeren, damit dieselbe Datei erneut ausgewählt werden kann.
  input.value = ''
  if (!file) return
  fileName.value = file.name
  try {
    rawText.value = await file.text()
  } catch {
    parsed.value = null
    parseError.value = 'Die Datei konnte nicht gelesen werden.'
  }
}

// ── Öffnen/Schließen ─────────────────────────────────────────────────────────

function onWindowKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape' && !submitting.value) close()
}

function close() {
  if (submitting.value) return
  emit('close')
}

function reset() {
  rawText.value = ''
  fileName.value = null
  parseError.value = null
  parsed.value = null
  targetKey.value = ''
  keyTouched.value = false
  keyError.value = null
  issues.value = []
  submitting.value = false
  zuordnung.value = {}
}

watch(() => props.open, (open) => {
  if (open) {
    reset()
    // Fachabteilungen für die Zuordnung bei jedem Öffnen frisch laden (der
    // Hinweistext schickt Nutzer:innen raus, um fehlende Fachabteilungen
    // anzulegen – beim Wiederkommen muss die neue auftauchen). Schlägt das
    // Laden fehl (leere Liste), erscheint keine Zuordnung und der Server löst
    // Platzhalter über den Namen auf bzw. lehnt mit einer klaren Meldung ab.
    const generation = ++ladeGeneration
    gruppen.value = []
    gruppenLaden.value = true
    loadGroupOptions().then((g) => {
      if (generation !== ladeGeneration) return
      gruppen.value = g
      gruppenLaden.value = false
    })
    window.addEventListener('keydown', onWindowKey)
    nextTick(() => textArea.value?.focus())
  } else {
    window.removeEventListener('keydown', onWindowKey)
  }
})

onUnmounted(() => window.removeEventListener('keydown', onWindowKey))

// ── Import ───────────────────────────────────────────────────────────────────

async function submit() {
  if (!canSubmit.value || !parsed.value) return
  submitting.value = true
  keyError.value = null
  issues.value = []
  try {
    // Gewählte Zuordnungen anwenden ('' und KEEP lassen den Wert stehen).
    // Quelle sind die AKTUELLEN Zeilen, nicht `zuordnung` selbst – dort können
    // nach JSON-Nachbesserungen Einträge zu Werten liegen, die es nicht mehr
    // gibt (oder die inzwischen eine bekannte Gruppe sind).
    const mapping: Record<string, string> = {}
    for (const r of unbekannte.value) {
      const gid = zuordnung.value[r.value]
      if (gid && gid !== KEEP) mapping[r.value] = gid
    }
    const defn = replaceGroupRefs(parsed.value, mapping)
    // Schlüssel in der Definition angleichen – maßgeblich ist ohnehin targetKey.
    const out = await importProcess(targetKey.value, { ...defn, key: targetKey.value })
    rememberKey(out.key)
    showToast(`Prozess „${out.name || out.key}“ importiert`)
    emit('imported', { key: out.key, version: out.version })
  } catch (e: any) {
    if (errorCode(e) === 'PROCESS_KEY_EXISTS') {
      keyError.value = 'Dieser Schlüssel ist bereits vergeben. Bitte einen anderen wählen.'
    } else if (isSystemReadonlyError(e)) {
      // Der Server nimmt einen System-Schlüssel als Ziel nicht an – am Feld
      // erklären, nicht als Toast: geändert werden muss der Ziel-Schlüssel.
      keyError.value = 'Dieser Schlüssel gehört zu einem System-Prozess und ist gesperrt. '
        + 'Bitte einen anderen wählen.'
    } else {
      const list = issuesFromError(e)
      if (list.length) issues.value = list
      else showToast(errorMessage(e, 'Import fehlgeschlagen'), false)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition enter-active-class="transition duration-150"
                enter-from-class="opacity-0" enter-to-class="opacity-100"
                leave-active-class="transition duration-100"
                leave-from-class="opacity-100" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
           @click.self="close()">
        <div class="bg-white dark:bg-[#212B3A] rounded-2xl shadow-xl w-full max-w-lg p-6 space-y-4
                    border border-gray-200 dark:border-white/[0.09]
                    max-h-[90vh] overflow-y-auto">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">Prozess importieren</h3>
          <p class="text-sm text-gray-600 dark:text-gray-300">
            Exportdatei auswählen oder JSON einfügen. Der Import legt einen neuen Entwurf an –
            veröffentlicht wird nichts automatisch.
          </p>

          <!-- Datei -->
          <div>
            <label class="lbl">Datei</label>
            <input type="file" accept=".json,application/json" @change="onFile"
                   class="block w-full text-sm text-gray-600 dark:text-gray-300 cursor-pointer
                          file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0
                          file:text-sm file:font-medium file:cursor-pointer
                          file:bg-[#3EAAB8]/10 file:text-[#3EAAB8] hover:file:bg-[#3EAAB8]/15" />
            <p v-if="fileName" class="text-xs text-gray-400 mt-1">Gewählt: {{ fileName }}</p>
          </div>

          <!-- Einfügen -->
          <div>
            <label class="lbl">…oder JSON einfügen</label>
            <textarea ref="textArea" v-model="rawText" rows="6" spellcheck="false"
                      placeholder='{ "schemaVersion": 1, "key": "…", "name": "…", … }'
                      class="set-input w-full font-mono text-xs resize-none" />
          </div>

          <p v-if="parseError"
             class="rounded-xl border border-red-300 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                    px-4 py-3 text-sm text-red-800 dark:text-red-300">
            {{ parseError }}
          </p>

          <!-- Erkannter Inhalt -->
          <div v-if="parsed"
               class="rounded-xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-[#1A2130]
                      px-4 py-3 text-sm space-y-1">
            <div class="text-gray-700 dark:text-gray-200">
              Erkannt: <span class="font-medium">{{ parsed.name || 'Ohne Namen' }}</span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">
              Schlüssel im JSON: <span class="font-mono">{{ parsed.key || '—' }}</span>
              · {{ parsed.phases.length }} Phasen · {{ parsed.fields.length }} Felder
            </div>
            <p v-if="structureHint" class="text-xs text-amber-700 dark:text-amber-300">
              {{ structureHint }}
            </p>
          </div>

          <!-- Fremde Fachabteilungen zuordnen -->
          <div v-if="unbekannte.length"
               class="rounded-xl border border-amber-300 dark:border-amber-500/30
                      bg-amber-50 dark:bg-amber-900/15 px-4 py-3 space-y-3">
            <div>
              <p class="text-sm font-semibold text-amber-900 dark:text-amber-200">
                Fachabteilungen zuordnen
              </p>
              <p class="text-xs text-amber-800 dark:text-amber-300/80 mt-0.5">
                Die Vorlage verweist auf Fachabteilungen, die es hier nicht als ID gibt.
                Bitte jede einer Fachabteilung <span class="font-medium">dieser Umgebung</span>
                zuordnen – die IDs sind in Dev und Prod verschieden. Die Wahl wird beim
                Import an allen Stellen übernommen.
              </p>
            </div>
            <div v-for="r in unbekannte" :key="r.value"
                 class="flex items-center gap-3">
              <div class="flex-1 min-w-0">
                <p :class="['truncate text-amber-900 dark:text-amber-100',
                            r.placeholder ? 'text-sm font-medium' : 'font-mono text-xs']">
                  {{ r.label }}
                </p>
                <p class="text-[11px] text-amber-700/70 dark:text-amber-300/60">
                  {{ r.placeholder ? 'Platzhalter aus der Vorlage' : 'Unbekannte Gruppen-ID' }}
                  · {{ r.sites }} {{ r.sites === 1 ? 'Stelle' : 'Stellen' }}
                </p>
              </div>
              <select v-model="zuordnung[r.value]"
                      :class="['set-input w-52 shrink-0 text-sm',
                               zuordnung[r.value] ? '' : 'border-amber-400 dark:border-amber-500/50']">
                <option value="" disabled>Bitte wählen…</option>
                <option v-if="!r.placeholder" :value="KEEP">Unverändert übernehmen</option>
                <option v-for="g in gruppenSortiert" :key="g.id" :value="g.id">
                  {{ g.name }}
                </option>
              </select>
            </div>
            <p v-if="offeneZuordnungen" class="text-xs text-amber-800 dark:text-amber-300">
              Noch {{ offeneZuordnungen }}
              {{ offeneZuordnungen === 1 ? 'Zuordnung offen' : 'Zuordnungen offen' }}. Fehlt eine
              Fachabteilung ganz, bitte zuerst unter „Fachabteilungen" anlegen und den Import
              erneut öffnen.
            </p>
          </div>

          <!-- Ziel-Schlüssel -->
          <div v-if="parsed">
            <label class="lbl">Ziel-Schlüssel</label>
            <input v-model="targetKey" @input="keyTouched = true" spellcheck="false" autocomplete="off"
                   :class="['set-input w-full font-mono',
                            keyError ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : '']"
                   placeholder="onboarding-mitarbeitende" />
            <p v-if="keyError" class="text-xs text-red-500 mt-1">{{ keyError }}</p>
            <p v-else-if="targetKey && !keyValid" class="text-xs text-red-500 mt-1">
              Ungültiger Schlüssel. {{ KEY_RULE }}
            </p>
            <p v-else class="text-xs text-gray-400 mt-1">
              Unter diesem Schlüssel wird angelegt – bitte bestätigen oder überschreiben.
            </p>
          </div>

          <!-- Serverseitige Feldfehler -->
          <div v-if="issues.length"
               class="rounded-xl border border-red-300 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-300">
            <p class="font-semibold mb-1">Die Definition wurde abgelehnt:</p>
            <ul class="space-y-0.5">
              <li v-for="(i, idx) in issues" :key="idx" class="text-xs">
                <span v-if="i.path !== 'body'" class="font-mono">{{ i.path }}</span>
                <span v-if="i.path !== 'body'"> · </span>{{ i.message }}
              </li>
            </ul>
          </div>

          <p v-if="parsed && gruppenLaden" class="text-xs text-gray-400">
            Fachabteilungen werden geladen, einen Moment…
          </p>

          <div class="flex justify-end gap-3 pt-2">
            <button @click="close()" :disabled="submitting"
                    class="px-4 py-2 rounded-xl text-sm
                           bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200
                           hover:bg-gray-200 dark:hover:bg-white/15 disabled:opacity-50 transition">
              Abbrechen
            </button>
            <button @click="submit()" :disabled="!canSubmit"
                    class="px-4 py-2 rounded-xl text-sm font-medium
                           bg-[#3EAAB8] hover:bg-[#2B7D89] text-white transition
                           disabled:opacity-50 disabled:cursor-not-allowed">
              {{ submitting ? 'Importiere…' : 'Importieren' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
