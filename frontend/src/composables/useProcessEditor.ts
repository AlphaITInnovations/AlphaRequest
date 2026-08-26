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
import { loadOptionSources } from '@/lib/processSources'
import { renameRefsInDefinition } from '@/lib/processRename'
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
  /** ALLE Automations-IDs (prozessweit + je Phase) – Eindeutigkeit gilt global. */
  const automationIds = computed(() => [
    ...(draft.value?.automations ?? []),
    ...(draft.value?.phases ?? []).flatMap((p) => p.automations),
  ].map((a) => a.id))

  const fieldLabels = computed(() => {
    const out: Record<string, string> = {}
    for (const f of draft.value?.fields ?? []) out[f.key] = f.label || f.key
    return out
  })

  /** Feld-Key → Widget (für Editoren, die den Feldtyp brauchen, z. B. „Firma
   *  als alphacore-ID auflösen“ nur bei widget=company). */
  const fieldWidgets = computed(() => {
    const out: Record<string, string> = {}
    for (const f of draft.value?.fields ?? []) out[f.key] = f.widget
    return out
  })

  async function loadSources() {
    // Admin-Variante: /settings/groups liefert auch versteckte Gruppen – sonst
    // sähen gültige Gruppen im Editor wie Tippfehler aus.
    const loaded = await loadOptionSources(true)
    sources.groups = loaded.groups
    sources.users = loaded.users
    sources.companies = loaded.companies
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

  /**
   * Feld-Umbenennung: zieht die Referenzen strukturell nach.
   *
   * WICHTIG: bewusst KEIN blindes Ersetzen aller gleichlautenden Strings – das
   * würde auch Options-Werte, Meldungstexte, Phasen-Schlüssel oder gar den
   * Prozess-Key mit umbenennen (Phasen- und Feld-Alphabet überschneiden sich).
   * Angefasst werden nur echte Referenzpositionen.
   */
  function renameFieldKey(from: string, to: string) {
    if (!draft.value || from === to || !from || !to) return
    draft.value = renameRefsInDefinition(draft.value, from, to)
    if (serverIssues.value.length) serverIssues.value = []
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
    sources, fieldKeys, fieldLabels, fieldWidgets, automationIds,
    load, loadSources, update, renameFieldKey, save, publish, reloadFromServer, revert,
  }
}
