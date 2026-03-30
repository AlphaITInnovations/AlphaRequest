import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'
export interface UserRef { id: string; name: string }

export interface MarketingStelleForm {
  accountable:  UserRef | null
  assignee:     UserRef | null
  priority:     TicketPriority
  comment:      string

  stelle: {
    // Antragsteller (read-only)
    antragsteller_name:  string
    antragsteller_email: string

    // Freigabe erteilt durch (read-only, same as antragsteller)
    freigabe_name:  string
    freigabe_email: string

    // Niederlassung & Gesellschaft
    niederlassung:  string
    gesellschaften: string[]

    // Stelle
    berufsbezeichnung:   string
    beschaeftigungsart:  string
    kostenstelle:        string

    // Kampagnenverantwortlicher
    talention_verantwortlicher_id:   string
    talention_verantwortlicher_name: string

    // Stellendetails
    benefits:              string
    gehaltsangabe:         string
    gehalt:                string
    bedingungen_notwendig: string
    qualifikationen_nice:  string

    // Anzeige
    online_datum:   string
    open_end:       string
    end_datum:      string
    staedte:        string
    radius:         string
    budget:         string

    // Funnel
    vorqualifizierung_fragen:       string[]
    vorqualifizierung_custom:       string[]   // mehrere custom-Einträge
    faq:                            string
  }
}

const GESELLSCHAFTEN = [
  'AlphaConsult KG',
  'AlphaConsult Premium KG',
  'Alpha-Med KG',
  'Alpha-Students GmbH',
  'Alpha-Engineering KG',
  'Alpha-Aviation GmbH',
  'Alpha-Business-Solutions',
  'Modern Business Solutions',
  'Alpha-IT Innovations',
]

const VORQUALIFIZIERUNG_OPTIONEN = [
  'Ab wann könntest du starten? (Sofort / Datum / in X Wochen)',
  'Welche Deutschkenntnisse hast du? (Fließend / gut / basics / keine)',
  'Hast du bereits Berufserfahrung? (Keine / 0–1 / 1–3 / 3+ Jahre)',
  'Welche Arbeitszeiten passen dir am besten? (tagsüber / früh / spät / nacht / flexibel)',
  'Schichtarbeit möglich? (Ja / Nein / nur bestimmte Schicht)',
  'Zu welchen Uhrzeiten bist du gut erreichbar?',
]

export { GESELLSCHAFTEN, VORQUALIFIZIERUNG_OPTIONEN }

type Rule = {
  required?: boolean
  requiredIf?: (f: MarketingStelleForm, phase: Phase) => boolean
}

// Pflichtfelder bei Erstellung: nur Antragsteller-Block + Verantwortlicher
// Alle anderen Felder: erst bei Bearbeitung (edit) Pflicht
const RULES: Record<string, Rule> = {
  'accountable':                           { required: true },
  'stelle.talention_verantwortlicher_id':  { requiredIf: (_, p) => p === 'edit' },

  // Ab hier nur bei edit Pflicht
  'stelle.niederlassung':         { requiredIf: (_, p) => p === 'edit' },
  'stelle.berufsbezeichnung':     { requiredIf: (_, p) => p === 'edit' },
  'stelle.beschaeftigungsart':    { requiredIf: (_, p) => p === 'edit' },
  'stelle.kostenstelle':          { requiredIf: (_, p) => p === 'edit' },
  'stelle.benefits':              { requiredIf: (_, p) => p === 'edit' },
  'stelle.gehaltsangabe':         { requiredIf: (_, p) => p === 'edit' },
  'stelle.gehalt':                { requiredIf: (f, p) => p === 'edit' && f.stelle.gehaltsangabe === 'Ja' },
  'stelle.bedingungen_notwendig': { requiredIf: (_, p) => p === 'edit' },
  'stelle.online_datum':          { requiredIf: (_, p) => p === 'edit' },
  'stelle.open_end':              { requiredIf: (_, p) => p === 'edit' },
  'stelle.end_datum':             { requiredIf: (f, p) => p === 'edit' && f.stelle.open_end === 'Nein' },
  'stelle.staedte':               { requiredIf: (_, p) => p === 'edit' },
  'stelle.radius':                { requiredIf: (_, p) => p === 'edit' },
  'stelle.budget':                { requiredIf: (_, p) => p === 'edit' },
  'stelle.faq':                   { requiredIf: (_, p) => p === 'edit' },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

export function useMarketingStelle(phase: Phase, ticketId?: number) {
  const router = useRouter()
  const auth   = useAuthStore()

  const loading         = ref(false)
  const submitting      = ref(false)
  const validationTriggered = ref(false)
  const errors          = ref<string[]>([])
  const pendingConfirm  = ref(false)
  const pendingComplete = ref(false)

  const form = reactive<MarketingStelleForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    stelle: {
      antragsteller_name:  '',
      antragsteller_email: '',
      freigabe_name:       '',
      freigabe_email:      '',

      niederlassung:  '',
      gesellschaften: [],

      berufsbezeichnung:   '',
      beschaeftigungsart:  '',
      kostenstelle:        '',

      talention_verantwortlicher_id:   '',
      talention_verantwortlicher_name: '',

      benefits:              '',
      gehaltsangabe:         '',
      gehalt:                '',
      bedingungen_notwendig: '',
      qualifikationen_nice:  '',

      online_datum: '',
      open_end:     '',
      end_datum:    '',
      staedte:      '',
      radius:       '',
      budget:       '',

      vorqualifizierung_fragen: [],
      vorqualifizierung_custom: [],
      faq: '',
    },
  })

  function isEmpty(v: unknown): boolean {
    if (Array.isArray(v)) return v.length === 0
    return v === null || v === undefined || v === ''
  }

  function isInvalid(path: string): boolean {
    const rule = RULES[path]
    if (!rule) return false
    const value = path === 'accountable'
      ? form.accountable?.id
      : getDeep(form as unknown as Record<string, unknown>, path)
    if (rule.requiredIf) return rule.requiredIf(form, phase) && isEmpty(value)
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
    const failed = Object.keys(RULES).filter(p => isInvalid(p))
    if (phase === 'edit' && form.stelle.gesellschaften.length === 0)
      failed.push('stelle.gesellschaften')
    errors.value = failed
    if (failed.length > 0) { window.scrollTo({ top: 0, behavior: 'smooth' }); return false }
    return true
  }

  async function init() {
    loading.value = true
    try {
      if (phase === 'create') {
        const name  = auth.user?.displayName ?? ''
        const email = auth.user?.mail ?? ''
        form.stelle.antragsteller_name  = name
        form.stelle.antragsteller_email = email
        form.stelle.freigabe_name       = name
        form.stelle.freigabe_email      = email
      }

      if (phase === 'edit' && ticketId) {
        const res  = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t    = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.stelle) Object.assign(form.stelle, desc.stelle)
        form.priority    = t.priority as TicketPriority
        form.comment     = t.comment ?? ''
        form.assignee    = t.assignee_id    ? { id: t.assignee_id,    name: t.assignee_name }    : null
        form.accountable = t.accountable_id ? { id: t.accountable_id, name: t.accountable_name } : null
      }
    } finally {
      loading.value = false
    }
  }

  function buildDescription(): string {
    return JSON.stringify({ stelle: form.stelle })
  }

  async function submitCreate() {
    if (!validate()) return
    pendingConfirm.value = true
  }

  async function confirmCreate() {
    if (!form.accountable) return
    submitting.value = true
    pendingConfirm.value = false
    try {
      await client.post('/tickets', {
        ticket_type:      'marketing-stellenanzeige',
        description:      buildDescription(),
        assignee_id:      form.accountable.id,
        assignee_name:    form.accountable.name,
        accountable_id:   form.accountable.id,
        accountable_name: form.accountable.name,
        priority:         form.priority,
        comment:          form.comment,
      })
      router.push('/dashboard')
    } catch {
      alert('Fehler beim Erstellen des Tickets')
    } finally {
      submitting.value = false
    }
  }

  async function submitEdit(action: 'save' | 'complete') {
    if (!validate() || !ticketId) return
    if (action === 'complete') { pendingComplete.value = true; return }
    await _performEdit('save')
  }

  async function confirmComplete() {
    pendingComplete.value = false
    await _performEdit('complete')
  }

  async function _performEdit(action: 'save' | 'complete') {
    if (!ticketId) return
    submitting.value = true
    try {
      await client.patch(`/tickets/${ticketId}`, {
        description:      buildDescription(),
        priority:         form.priority,
        comment:          form.comment,
        assignee_id:      form.assignee?.id,
        assignee_name:    form.assignee?.name,
        accountable_id:   form.accountable?.id,
        accountable_name: form.accountable?.name,
      })
      if (action === 'complete') await client.post(`/tickets/${ticketId}/submit`)
      router.push('/dashboard')
    } catch {
      alert('Fehler beim Speichern')
    } finally {
      submitting.value = false
    }
  }

  return {
    form, loading, submitting,
    pendingConfirm, pendingComplete,
    validationTriggered, errors,
    init, validate, isInvalid, fieldClass,
    submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}