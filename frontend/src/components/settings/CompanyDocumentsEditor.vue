<script setup lang="ts">
/**
 * Benannte Dokument-Vorlagen (.docx/PDF) EINER Firma verwalten – Teil des
 * Firmen-Detail-Editors. Ein Prozess-Dokument referenziert eine Vorlage nur über
 * ihren Namen; welche Datei gefüllt wird, entscheidet die im Auftrag gewählte Firma.
 */
import { ref, watch } from 'vue'
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
}>()

const { showToast } = useToast()
const docs = ref<CompanyDocument[]>([])
const loading = ref(false)
const newName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

async function reload() {
  if (!props.ready || !props.company) { docs.value = []; return }
  loading.value = true
  try {
    docs.value = await listCompanyDocuments(props.company)
  } catch {
    docs.value = []
  } finally {
    loading.value = false
  }
}

watch(() => [props.company, props.ready], reload, { immediate: true })

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
          <button type="button" @click="remove(d.name)"
                  class="text-xs text-red-500 hover:text-red-600 hover:underline whitespace-nowrap">Entfernen</button>
        </li>
      </ul>
      <p v-else-if="!loading" class="text-xs text-gray-400 italic mb-2">Noch keine Vorlagen hinterlegt.</p>

      <div class="flex items-center gap-2">
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
