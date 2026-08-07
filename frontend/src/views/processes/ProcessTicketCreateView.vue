<script setup lang="ts">
/**
 * Auftrag aus einem veröffentlichten Prozess anlegen.
 * Das Formular wird vollständig aus der Prozess-Definition gerendert.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition, ProcessOut } from '@/types/process'
import type { SimFieldError } from '@/lib/processSim'
import { validatePhaseCompletion, validateValues } from '@/lib/processSim'
import { normalizeDefinition } from '@/lib/processNormalize'
import { errorMessage, issuesFromError } from '@/lib/processErrors'
import { PRIORITIES } from '@/lib/processSchema'
import * as processesApi from '@/api/processes'
import { createTicket } from '@/api/processTickets'
import { client } from '@/api/client'
import SchemaForm from '@/components/process/form/SchemaForm.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()

const loading = ref(true)
const submitting = ref(false)
const catalog = ref<ProcessOut[]>([])
const selectedKey = ref<string>(String(route.params.key || ''))
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const title = ref('')
const priority = ref('normal')
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>({ groups: [], users: [], companies: [] })

/** Aus Sicht der erstellenden Person: Owner ⇒ Vollsicht. */
const viewer = { fullView: true, isAdmin: false, groupIds: [] }

const startPhase = computed(() => definition.value?.phases?.[0] ?? null)

async function loadSources() {
  try {
    const { data } = await client.get('/settings/groups')
    sources.value.groups = (data.data || []).map((g: any) => ({ id: g.id, name: g.name }))
  } catch { /* Namen sind optional */ }
  try {
    const { data } = await client.get('/users')
    const list = data.data || data || []
    sources.value.users = list.map((u: any) => ({ id: u.id, displayName: u.displayName || u.id }))
  } catch { /* optional */ }
  try {
    const { data } = await client.get('/companies')
    const list = data.data || data || []
    sources.value.companies = list.map((c: any) => (typeof c === 'string' ? c : c.name)).filter(Boolean)
  } catch { /* optional */ }
}

async function loadProcess(key: string) {
  if (!key) { definition.value = null; return }
  try {
    const row = await processesApi.getPublished(key)
    definition.value = normalizeDefinition(row.definition)
    title.value = row.name
    values.value = {}
    errors.value = []
  } catch (e) {
    definition.value = null
    showToast(errorMessage(e, 'Prozess konnte nicht geladen werden'), false)
  }
}

async function submit() {
  if (!definition.value || !startPhase.value) return
  // Client-Vorprüfung (der Server prüft erneut und ist maßgeblich)
  const shapeErrors = validateValues(definition.value, values.value)
  const requiredErrors = validatePhaseCompletion(definition.value, startPhase.value, values.value)
  errors.value = [...shapeErrors, ...requiredErrors]
  if (errors.value.length) {
    showToast('Bitte die markierten Felder prüfen', false)
    return
  }
  submitting.value = true
  try {
    const t = await createTicket({
      processKey: definition.value.key,
      title: title.value || null,
      priority: priority.value,
      values: values.value,
    })
    showToast('Auftrag angelegt')
    router.push(`/prozess-auftraege/${t.id}`)
  } catch (e) {
    const issues = issuesFromError(e)
    errors.value = issues.map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Anlegen fehlgeschlagen'), false)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadSources()
  try {
    catalog.value = await processesApi.listProcesses()
  } catch { /* Katalog optional, wenn der Key aus der Route kommt */ }
  if (selectedKey.value) await loadProcess(selectedKey.value)
  loading.value = false
})
</script>

<template>
  <AppLayout>
    <div class="max-w-4xl mx-auto px-4 py-6">
      <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 mb-4">Neuer Auftrag</h1>

      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <template v-else>
        <!-- Prozess-Auswahl -->
        <section class="card-section mb-4">
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Prozess</label>
          <select v-model="selectedKey" class="afi w-full" @change="loadProcess(selectedKey)">
            <option value="">– bitte wählen –</option>
            <option v-for="p in catalog" :key="p.key" :value="p.key">
              {{ p.definition?.icon || '' }} {{ p.name }}
            </option>
          </select>
          <p v-if="!catalog.length" class="text-xs text-gray-400 mt-2">
            Es ist noch kein Prozess veröffentlicht.
          </p>
        </section>

        <template v-if="definition && startPhase">
          <section class="card-section mb-4">
            <div class="grid md:grid-cols-3 gap-3">
              <div class="md:col-span-2">
                <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel</label>
                <input v-model="title" class="afi w-full" maxlength="255" />
              </div>
              <div>
                <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Priorität</label>
                <select v-model="priority" class="afi w-full">
                  <option v-for="p in PRIORITIES" :key="p" :value="p">{{ p }}</option>
                </select>
              </div>
            </div>
          </section>

          <SchemaForm :definition="definition" :phase="startPhase" :model-value="values"
                      :viewer="viewer" :errors="errors" :sources="sources"
                      @update:model-value="values = $event" />

          <div class="flex justify-end gap-2 mt-4">
            <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
            <button @click="submit" :disabled="submitting"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">
              {{ submitting ? 'Wird angelegt…' : 'Auftrag anlegen' }}
            </button>
          </div>
        </template>
      </template>
    </div>
  </AppLayout>
</template>
