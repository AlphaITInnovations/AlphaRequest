<script setup lang="ts">
/**
 * Benannte Dokument-Vorlagen (.docx/PDF) EINER Firma verwalten – Teil des
 * Firmen-Detail-Editors. Ein Prozess-Dokument referenziert eine Vorlage nur über
 * ihren Namen; welche Datei gefüllt wird, entscheidet die im Auftrag gewählte Firma.
 *
 * Übernimmt die Firma Vorlagen von einer anderen (sharedWith gesetzt), zeigt der
 * Editor DEREN Vorlagen read-only; eigene lassen sich dann nicht hochladen. Weil die
 * Übernahme eine Entweder-oder-Einstellung ist (Firma mit eigenen Vorlagen lässt sich
 * nicht umstellen), warnt der Editor, solange noch eigene Vorlagen übrig sind, und
 * bietet dort das Entfernen an. Die Anzeige richtet sich nach der NOCH NICHT
 * gespeicherten Auswahl (sharedWith-Prop), nicht nach dem DB-Stand.
 */
import { computed, ref, watch } from 'vue'
import { useToast } from '@/composables/useToast'
import type { CompanyDocument } from '@/api/companyDocuments'
import {
  companyDocumentDownloadUrl, deleteCompanyDocument,
  listCompanyDocuments, uploadCompanyDocument,
} from '@/api/companyDocuments'

const props = defineProps<{
  company: string
  /** Firma serverseitig gespeichert (sonst erst speichern, dann Vorlagen). */
  ready: boolean
  /** Aktuell (ggf. ungespeichert) gewählte Quell-Firma, deren Vorlagen übernommen
   *  werden – null = eigene Vorlagen. */
  sharedWith: string | null
}>()

const { showToast } = useToast()
/** Im Übernahme-Modus die Vorlagen der Quelle (read-only), sonst die eigenen. */
const docs = ref<CompanyDocument[]>([])
/** Noch vorhandene EIGENE Vorlagen, während „übernehmen“ gewählt ist – blockieren
 *  das Speichern und müssen zuerst entfernt werden. */
const ownLeftover = ref<CompanyDocument[]>([])
const loading = ref(false)
const newName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

const inherits = computed(() => !!props.sharedWith)

async function reload() {
  if (!props.ready || !props.company) { docs.value = []; ownLeftover.value = []; return }
  loading.value = true
  try {
    if (props.sharedWith) {
      // Quelle direkt laden (sie besitzt die Vorlagen selbst) + eigenen Rest prüfen.
      const [src, own] = await Promise.all([
        listCompanyDocuments(props.sharedWith),
        listCompanyDocuments(props.company, { own: true }),
      ])
      docs.value = src.documents
      ownLeftover.value = own.documents
    } else {
      const res = await listCompanyDocuments(props.company, { own: true })
      docs.value = res.documents
      ownLeftover.value = []
    }
  } catch {
    docs.value = []
    ownLeftover.value = []
  } finally {
    loading.value = false
  }
}

watch(() => [props.company, props.ready, props.sharedWith], reload, { immediate: true })

function pick() {
  if (!newName.value.trim()) { showToast('Bitte zuerst einen Vorlagen-Namen angeben', false); return }
  fileInput.value?.click()
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const name = newName.value.trim()
  if (!name) return
  uploading.value = true
  try {
    await uploadCompanyDocument(props.company, name, file)
    newName.value = ''
    showToast(`Vorlage „${name}“ gespeichert`, true)
    await reload()
  } catch (err: any) {
    showToast(err?.response?.data?.detail || err?.response?.data?.error?.message
      || 'Hochladen fehlgeschlagen', false)
  } finally {
    uploading.value = false
  }
}

async function remove(name: string) {
  if (!confirm(`Vorlage „${name}“ wirklich entfernen?`)) return
  try {
    await deleteCompanyDocument(props.company, name)
    await reload()
  } catch {
    showToast('Entfernen fehlgeschlagen', false)
  }
}

// Download der eigenen Vorlagen geht an die Firma selbst; im Übernahme-Modus löst der
// Server die Quelle auf (gleicher Endpunkt), daher genügt hier props.company.
const dlUrl = (name: string) => companyDocumentDownloadUrl(props.company, name)
</script>

<template>
  <div>
    <label class="lbl">Dokument-Vorlagen <span class="text-gray-400 font-normal">(firmenabhängig)</span></label>
    <p class="text-xs text-gray-400 mb-2">
      Benannte Word-/PDF-Vorlagen dieser Firma (z. B. „Arbeitsvertrag“, „Kündigung“). Im Prozess
      wird eine Vorlage über ihren <b>Namen</b> eingebunden; gefüllt wird die Datei der im Auftrag
      gewählten Firma.
    </p>

    <p v-if="!ready" class="text-xs text-amber-600 dark:text-amber-400">
      Bitte die Firma zuerst speichern – danach lassen sich Vorlagen hinterlegen.
    </p>

    <template v-else>
      <!-- Übernahme gewählt, aber es liegen noch eigene Vorlagen vor → Speichern würde
           scheitern; hier entfernbar machen. -->
      <div v-if="inherits && ownLeftover.length"
           class="rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-900/20
                  px-3 py-2 mb-2 space-y-1.5">
        <p class="text-xs text-amber-800 dark:text-amber-200">
          Diese Firma hat noch eigene Vorlagen. Die Übernahme von „{{ sharedWith }}“ lässt sich erst
          speichern, wenn diese entfernt sind:
        </p>
        <ul class="space-y-1">
          <li v-for="d in ownLeftover" :key="d.name" class="flex items-center gap-2">
            <span class="text-sm font-medium text-gray-900 dark:text-white truncate">{{ d.name }}</span>
            <span class="text-xs text-gray-400 truncate min-w-0 flex-1">{{ d.filename }}</span>
            <button type="button" @click="remove(d.name)"
                    class="text-xs text-red-500 hover:text-red-600 hover:underline whitespace-nowrap">Entfernen</button>
          </li>
        </ul>
      </div>

      <!-- Übernimmt Vorlagen einer anderen Firma: nur Anzeige (read-only). -->
      <p v-if="inherits" class="text-xs rounded-lg bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-2 mb-2">
        🔗 Übernimmt die Vorlagen von „{{ sharedWith }}“. Verwaltet werden sie dort; hier zur Kontrolle angezeigt.
      </p>

      <ul v-if="docs.length" class="space-y-1.5 mb-3">
        <li v-for="d in docs" :key="d.name"
            class="flex items-center gap-2 rounded-lg border border-gray-200 dark:border-white/10
                   bg-gray-50 dark:bg-white/[0.03] px-3 py-2">
          <span class="text-sm font-medium text-gray-900 dark:text-white truncate">{{ d.name }}</span>
          <span class="text-[11px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 uppercase">
            {{ d.format || '—' }}
          </span>
          <span class="text-xs text-gray-400 truncate min-w-0 flex-1">{{ d.filename }}</span>
          <a :href="dlUrl(d.name)" class="text-xs text-[#3EAAB8] hover:underline whitespace-nowrap">Download</a>
          <button v-if="!inherits" type="button" @click="remove(d.name)"
                  class="text-xs text-red-500 hover:text-red-600 hover:underline whitespace-nowrap">Entfernen</button>
        </li>
      </ul>
      <p v-else-if="!loading && !inherits" class="text-xs text-gray-400 italic mb-2">Noch keine Vorlagen hinterlegt.</p>
      <p v-else-if="!loading && inherits" class="text-xs text-gray-400 italic mb-2">
        „{{ sharedWith }}“ hat noch keine Vorlagen hinterlegt.
      </p>

      <div v-if="!inherits" class="flex items-center gap-2">
        <input v-model="newName" placeholder="Vorlagen-Name (z. B. Arbeitsvertrag)"
               class="set-input flex-1" :disabled="uploading" />
        <button type="button" @click="pick" :disabled="uploading"
                class="btn-secondary text-sm whitespace-nowrap disabled:opacity-40">
          {{ uploading ? 'Lädt…' : '+ Vorlage hochladen' }}
        </button>
        <input ref="fileInput" type="file" accept=".docx,.pdf" class="hidden" @change="onFile" />
      </div>
    </template>
  </div>
</template>
