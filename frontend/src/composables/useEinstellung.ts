import { ref, computed, reactive } from 'vue'
import { client } from '@/api/client'
import { companiesApi } from '@/api/companies'
import { ticketsApi } from '@/api/tickets'
import { useRouter } from 'vue-router'
import type { TicketPriority } from '@/types/ticket'

// ── Onboarding Prozess 1: „Einstellung Mitarbeiter:in" ──────────────────────────
// Erfasst Basisdaten + vertrauliche Informationen (Gehalt/Konditionen). Der Ablauf:
// Erstellung (Vorgesetzte:r) → Freigabe (Udo Lutz) → Arbeitsvertrag (Sekretariat GL)
// → Warten auf Vertragsrücklauf. Beim Rücklauf erzeugt das Backend automatisch
// Prozess 2 (zugang-beantragen).

export type Phase = 'create' | 'edit'
export type EinstellungStage = 'erstellung' | 'freigabe' | 'vertrag' | 'vertragsruecklauf'

export interface EinstellungForm {
  priority: TicketPriority
  comment:  string

  base: {
    salutation:       string
    first_name:       string
    last_name:        string
    contract_company: string
    location:         string
    cost_center:      string
    start_date:       string
  }
  // Titel (Berufsbezeichnung) – für den Arbeitsvertrag; wandert später in P2.
  title: string
  // Vertrauliche Informationen – NICHT für Fachabteilungen sichtbar (eigener Block,
  // steht in keiner Sichtbarkeits-Registry ⇒ nur Voll-Sicht sieht ihn).
  confidential: {
    salary:     string
    conditions: string
  }
}

type Rule = { required?: boolean }

const RULES_ERSTELLUNG: Record<string, Rule> = {
  'base.salutation':       { required: true },
  'base.first_name':       { required: true },
  'base.last_name':        { required: true },
  'base.contract_company': { required: true },
  'base.location':         { required: true },
  'base.cost_center':      { required: true },
  'base.start_date':       { required: true },
  'title':                 { required: true },
  // confidential.* bewusst optional (Freitext) – kann später verschärft werden.
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

export function useEinstellung(phase: Phase, ticketId?: number) {
  const router = useRouter()

  const companies   = ref<string[]>([])
  const loading     = ref(false)
  const submitting  = ref(false)
  const validationTriggered = ref(false)
  const errors      = ref<string[]>([])

  // Im Create immer 'erstellung'; im Edit aus der aktuellen Workflow-Phase.
  const stage = ref<EinstellungStage>('erstellung')

  const form = reactive<EinstellungForm>({
    priority: 'medium',
    comment:  '',
    base: {
      salutation: '', first_name: '', last_name: '',
      contract_company: '', location: '', cost_center: '', start_date: '',
    },
    title: '',
    confidential: { salary: '', conditions: '' },
  })

  // ── Validierung (nur bei der Erstellung greifen Pflichtfelder) ──────────────
  const rules = computed(() => (stage.value === 'erstellung' ? RULES_ERSTELLUNG : {}))

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === ''
  }
  function isInvalid(path: string): boolean {
    const rule = rules.value[path]
    if (!rule) return false
    const value = getDeep(form as unknown as Record<string, unknown>, path)
    return !!rule.required && isEmpty(value)
  }
  function fieldClass(path: string): string {
    const base = 'w-full rounded-xl border px-3.5 py-2.5 text-sm transition focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500'
    const err  = 'border-red-400 bg-red-50 dark:bg-red-900/20'
    const ok   = 'border-gray-200 dark:border-white/10'
    return `${base} ${validationTriggered.value && isInvalid(path) ? err : ok}`
  }
  function validate(): boolean {
    validationTriggered.value = true
    errors.value = Object.keys(rules.value).filter(p => isInvalid(p))
    if (errors.value.length) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return false
    }
    return true
  }

  // ── Beschriftung des Abschluss-Buttons je Phase ─────────────────────────────
  const completeLabel = computed(() => {
    if (stage.value === 'vertrag') return 'Arbeitsvertrag versendet'
    if (stage.value === 'vertragsruecklauf') return 'Vertrag zurück – Onboarding starten'
    return 'Abschließen'
  })

  // ── Laden ───────────────────────────────────────────────────────────────────
  async function init() {
    loading.value = true
    try {
      const { data: compData } = await companiesApi.list()
      companies.value = compData.data.companies

      if (phase === 'edit' && ticketId) {
        const res = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t = res.data.data
        const desc = JSON.parse(t.description || '{}')

        const wf = t.workflow_state
        const curKey = wf?.phases?.[wf?.current_phase_index ?? 0]?.key
        if (['freigabe', 'vertrag', 'vertragsruecklauf'].includes(curKey)) {
          stage.value = curKey
        }

        if (desc.base) Object.assign(form.base, desc.base)
        if (desc.personal?.title != null) form.title = desc.personal.title
        if (desc.confidential) Object.assign(form.confidential, desc.confidential)

        form.priority = t.priority as TicketPriority
        form.comment  = t.comment ?? ''
      }
    } finally {
      loading.value = false
    }
  }

  // ── Beschreibung bauen ──────────────────────────────────────────────────────
  function buildDescriptionObject(): Record<string, any> {
    return {
      base: { ...form.base },
      personal: { title: form.title },
      confidential: { ...form.confidential },
    }
  }
  function buildDescription(): string {
    return JSON.stringify(buildDescriptionObject())
  }
  // Für die read-only Zusammenfassung in den Bearbeitungsphasen.
  const descPreview = computed(() => buildDescriptionObject())

  // ── Erstellen ─────────────────────────────────────────────────────────────────
  const pendingConfirm  = ref(false)
  const pendingComplete = ref(false)

  async function submitCreate() {
    if (!validate()) return
    pendingConfirm.value = true
  }
  async function confirmCreate() {
    submitting.value = true
    pendingConfirm.value = false
    try {
      await client.post('/tickets', {
        ticket_type: 'einstellung',
        description: buildDescription(),
        priority:    form.priority,
        comment:     form.comment,
      })
      router.push('/dashboard')
    } catch (e: any) {
      alert(e?.response?.data?.detail?.message
          ?? e?.response?.data?.error?.message
          ?? 'Fehler beim Erstellen des Tickets')
    } finally {
      submitting.value = false
    }
  }

  // ── Bearbeiten (Vertrag versendet / Vertrag zurück) ─────────────────────────
  async function submitEdit(action: 'save' | 'complete') {
    if (!ticketId) return
    if (action === 'complete') { pendingComplete.value = true; return }
    await performEdit('save')
  }
  async function confirmComplete() {
    pendingComplete.value = false
    await performEdit('complete')
  }
  async function performEdit(action: 'save' | 'complete') {
    if (!ticketId) return
    submitting.value = true
    try {
      // Basis/Vertrauliches bleiben in diesen Phasen unverändert; PATCH hält den
      // Stand konsistent (und erlaubt eine spätere Notfall-Bearbeitung).
      await client.patch(`/tickets/${ticketId}`, {
        description: buildDescription(),
        priority:    form.priority,
        comment:     form.comment,
      })
      if (action === 'complete') {
        await ticketsApi.submit(ticketId)
      }
      router.push('/dashboard')
    } catch (e: any) {
      alert(e?.response?.data?.detail?.message
          ?? e?.response?.data?.error?.message
          ?? 'Aktion fehlgeschlagen')
    } finally {
      submitting.value = false
    }
  }

  return {
    form, companies, loading, submitting, stage,
    validationTriggered, errors, fieldClass, isInvalid, validate,
    completeLabel, descPreview,
    init, buildDescription,
    submitCreate, confirmCreate, pendingConfirm,
    submitEdit, confirmComplete, pendingComplete,
  }
}
