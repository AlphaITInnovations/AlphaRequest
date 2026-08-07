/**
 * Zustand und Aktionen des Prozess-Editors.
 *
 * Kernpunkte:
 *  - Es wird IMMER die normalisierte Form bearbeitet (siehe processNormalize),
 *    damit der Dirty-Vergleich stabil ist.
 *  - Gespeichert wird mit If-Match (etag aus dem Antwort-BODY, nicht dem Header);
 *    bei 409 PROCESS_VERSION_CONFLICT wird der Konflikt gemeldet statt überschrieben.
 *  - Nur Entwürfe sind editierbar; veröffentlichte/archivierte Versionen werden
 *    schreibgeschützt geladen.
 */
import { computed, reactive, ref, shallowRef } from 'vue'
import type { OptionSources, ProcessDefinition, ProcessIssue, ProcessOut } from '@/types/process'
import * as api from '@/api/processes'
import { client } from '@/api/client'
import { canonicalJson, cloneDefinition, normalizeDefinition } from '@/lib/processNormalize'
import { errorCode, errorMessage, issuesFromError } from '@/lib/processErrors'
import { errorCount, validateDefinition } from '@/lib/processValidate'

export function useProcessEditor() {
  const loading = ref(false)
  const saving = ref(false)
  const meta = ref<ProcessOut | null>(null)
  const draft = shallowRef<ProcessDefinition | null>(null)
  const baseline = ref<string>('')          // canonicalJson des zuletzt gespeicherten Stands
  const serverIssues = ref<ProcessIssue[]>([])
  const conflict = ref(false)
  const loadError = ref<string | null>(null)

  const sources = reactive<OptionSources>({ groups: [], users: [], companies: [] })

  const isDraft = computed(() => meta.value?.status === 'draft')
  const readonly = computed(() => !isDraft.value)

  const dirty = computed(() =>
    !!draft.value && canonicalJson(draft.value) !== baseline.value)

  const clientIssues = computed<ProcessIssue[]>(() => {
    if (!draft.value) return []
    return validateDefinition(draft.value, new Set(sources.groups.map((g) => g.id)))
  })

  const issues = computed<ProcessIssue[]>(() => [...clientIssues.value, ...serverIssues.value])
  const errors = computed(() => errorCount(issues.value))
  const warnings = computed(() => issues.value.filter((i) => i.severity === 'warning').length)
  const canSave = computed(() => isDraft.value && dirty.value && errors.value === 0 && !saving.value)
  const canPublish = computed(() => isDraft.value && !dirty.value && errors.value === 0)

  /** Feld-Schlüssel und -Beschriftungen für Picker in den Unter-Editoren. */
  const fieldKeys = computed(() => draft.value?.fields.map((f) => f.key) ?? [])
  const fieldLabels = computed(() => {
    const out: Record<string, string> = {}
    for (const f of draft.value?.fields ?? []) out[f.key] = f.label || f.key
    return out
  })

  async function loadSources() {
    // Fachabteilungen aus den Settings (enthält auch versteckte – sonst sähen
    // gültige Gruppen im Editor wie Tippfehler aus).
    try {
      const { data } = await client.get('/settings/groups')
      sources.groups = (data.data || []).map((g: any) => ({ id: g.id, name: g.name }))
    } catch { /* ohne Gruppen bleibt der Editor nutzbar, nur ohne Namen */ }
    try {
      const { data } = await client.get('/users')
      const list = data.data || data || []
      sources.users = list.map((u: any) => ({ id: u.id, displayName: u.displayName || u.name || u.id }))
    } catch { /* optional */ }
    try {
      const { data } = await client.get('/companies')
      const list = data.data || data || []
      sources.companies = list.map((c: any) => (typeof c === 'string' ? c : c.name)).filter(Boolean)
    } catch { /* optional */ }
  }

  async function load(key: string, version: number) {
    loading.value = true
    loadError.value = null
    conflict.value = false
    serverIssues.value = []
    try {
      const row = await api.getVersion(key, version)
      meta.value = row
      const defn = normalizeDefinition(row.definition ?? { key: row.key, name: row.name })
      draft.value = defn
      baseline.value = canonicalJson(defn)
    } catch (e) {
      loadError.value = errorMessage(e, 'Prozess konnte nicht geladen werden')
    } finally {
      loading.value = false
    }
  }

  function update(next: ProcessDefinition) {
    draft.value = next
    // Server-Fehler beziehen sich auf den alten Stand – beim Weiterarbeiten löschen.
    if (serverIssues.value.length) serverIssues.value = []
  }

  /** Feld-Umbenennung: alle Referenzen mitziehen (Phasen, Bedingungen, Automationen). */
  function renameFieldKey(from: string, to: string) {
    if (!draft.value || from === to || !from) return
    const json = JSON.stringify(draft.value)
    // Referenzen sind immer vollständige Strings – gezielt ersetzen statt global.
    const next = normalizeDefinition(JSON.parse(json, (_k, v) => (v === from ? to : v)))
    draft.value = next
  }

  async function save(): Promise<boolean> {
    if (!draft.value || !meta.value) return false
    saving.value = true
    serverIssues.value = []
    conflict.value = false
    try {
      const row = await api.saveDraft(meta.value.key, meta.value.version, draft.value,
        meta.value.etag)
      meta.value = row
      const defn = normalizeDefinition(row.definition ?? draft.value)
      draft.value = defn
      baseline.value = canonicalJson(defn)
      return true
    } catch (e) {
      const code = errorCode(e)
      if (code === 'PROCESS_VERSION_CONFLICT') {
        conflict.value = true
      } else {
        serverIssues.value = issuesFromError(e)
      }
      return false
    } finally {
      saving.value = false
    }
  }

  async function publish(): Promise<boolean> {
    if (!meta.value) return false
    saving.value = true
    try {
      const before = meta.value.status
      const row = await api.publishVersion(meta.value.key, meta.value.version)
      meta.value = row
      return before !== row.status || row.status === 'published'
    } catch (e) {
      serverIssues.value = issuesFromError(e)
      return false
    } finally {
      saving.value = false
    }
  }

  /** Konflikt auflösen: Server-Stand neu laden (lokale Änderungen gehen verloren). */
  async function reloadFromServer() {
    if (!meta.value) return
    await load(meta.value.key, meta.value.version)
  }

  function revert() {
    if (!meta.value?.definition) return
    const defn = normalizeDefinition(meta.value.definition)
    draft.value = cloneDefinition(defn)
    baseline.value = canonicalJson(defn)
    serverIssues.value = []
  }

  return {
    loading, saving, meta, draft, dirty, readonly, isDraft, conflict, loadError,
    issues, clientIssues, serverIssues, errors, warnings, canSave, canPublish,
    sources, fieldKeys, fieldLabels,
    load, loadSources, update, renameFieldKey, save, publish, reloadFromServer, revert,
  }
}
