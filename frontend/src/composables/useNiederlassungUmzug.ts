import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { companiesApi } from '@/api/companies'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'
export interface UserRef { id: string; name: string }

export interface NiederlassungUmzugForm {
  accountable: UserRef | null
  assignee:    UserRef | null
  priority:    TicketPriority
  comment:     string

  miete_alt: {
    location:          string
    company:           string
    lease_action:      string
    lease_cancel_date: string
    lease_keep_reason: string
  }

  miete_neu: {
    location:                 string
    company:                  string
    sign_visible:             string
    reopening:                string
    cost_center:              string
    start_date:               string
    address:                  string
    location_supervisor_id:   string
    location_supervisor_name: string
    contact_person_id:        string
    contact_person_name:      string
  }

  it_alt: {
    confirm_dsl_cancel:      boolean
    confirm_landline_cancel: boolean
    network_hw_action:       string
    network_hw_other:        string
  }

  it_neu: {
    server_rack:      string
    network_cabling:  string
    line_installed:   string
    line_type:        string
    line_location:    string
    landlord_name:    string
    landlord_contact: string
  }

  marketing: { opening_hours: string }
  fuhrpark:  { pool_cars: string; pool_cars_from: string }
}

// ── Validation ────────────────────────────────────────────────────────────────

type Rule = {
  required?: boolean
  requiredIf?: (form: NiederlassungUmzugForm) => boolean
}

const RULES_CREATE: Record<string, Rule> = {
  'miete_alt.location':          { required: true },
  'miete_alt.company':           { required: true },
  'miete_alt.lease_action':      { required: true },
  'miete_alt.lease_cancel_date': { requiredIf: f => f.miete_alt.lease_action === 'cancel' },
  'miete_alt.lease_keep_reason': { requiredIf: f => f.miete_alt.lease_action === 'keep' },
  'miete_neu.location':          { required: true },
  'miete_neu.company':           { required: true },
  'miete_neu.sign_visible':      { required: true },
  'miete_neu.reopening':         { required: true },
  'miete_neu.cost_center':       { required: true },
  'miete_neu.start_date':        { required: true },
  'miete_neu.address':           { required: true },
  'miete_neu.location_supervisor_id': { required: true },
  'miete_neu.contact_person_id':      { required: true },
  'accountable':                 { required: true },
}

const RULES_EDIT: Record<string, Rule> = {
  ...RULES_CREATE,
  'it_alt.confirm_dsl_cancel':      { requiredIf: f => f.miete_alt.lease_action === 'cancel' },
  'it_alt.confirm_landline_cancel': { requiredIf: f => f.miete_alt.lease_action === 'cancel' },
  'it_neu.server_rack':     { required: true },
  'it_neu.network_cabling': { required: true },
  'it_neu.line_installed':  { required: true },
  'marketing.opening_hours': { required: true },
  'fuhrpark.pool_cars':      { required: true },
  'fuhrpark.pool_cars_from': { requiredIf: f => f.fuhrpark.pool_cars === 'Ja' },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useNiederlassungUmzug(phase: Phase, ticketId?: number) {
  const router              = useRouter()
  const companies           = ref<string[]>([])
  const loading             = ref(false)
  const submitting          = ref(false)
  const validationTriggered = ref(false)
  const errors              = ref<string[]>([])
  const pendingConfirm      = ref(false)
  const pendingComplete     = ref(false)

  const form = reactive<NiederlassungUmzugForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    miete_alt: { location: '', company: '', lease_action: '', lease_cancel_date: '', lease_keep_reason: '' },
    miete_neu: {
      location: '', company: '', sign_visible: '', reopening: '',
      cost_center: '', start_date: '', address: '',
      location_supervisor_id: '', location_supervisor_name: '',
      contact_person_id: '', contact_person_name: '',
    },
    it_alt: { confirm_dsl_cancel: false, confirm_landline_cancel: false, network_hw_action: '', network_hw_other: '' },
    it_neu: { server_rack: '', network_cabling: '', line_installed: '', line_type: '', line_location: '', landlord_name: '', landlord_contact: '' },
    marketing: { opening_hours: '' },
    fuhrpark:  { pool_cars: '', pool_cars_from: '' },
  })

  const rules = phase === 'create' ? RULES_CREATE : RULES_EDIT

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === '' || v === false
  }

  function isInvalid(path: string): boolean {
    const rule = rules[path]
    if (!rule) return false
    const value = path === 'accountable'
      ? form.accountable?.id
      : getDeep(form as unknown as Record<string, unknown>, path)
    if (rule.requiredIf) return rule.requiredIf(form) && isEmpty(value)
    if (rule.required && isEmpty(value)) return true
    return false
  }

  function fieldClass(path: string): string {
    const base = 'w-full rounded-xl border px-3.5 py-2.5 text-sm transition focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500'
    const err  = 'border-red-400 bg-red-50 dark:bg-red-900/20'
    const ok   = 'border-gray-200 dark:border-white/10'
    return `${base} ${validationTriggered.value && isInvalid(path) ? err : ok}`
  }

  function validate(): boolean {
    validationTriggered.value = true
    const failed = Object.keys(rules).filter(p => isInvalid(p))
    errors.value = failed
    if (failed.length > 0) { window.scrollTo({ top: 0, behavior: 'smooth' }); return false }
    return true
  }

  async function init() {
    loading.value = true
    try {
      const { data } = await companiesApi.list()
      companies.value = data.data.companies

      if (phase === 'edit' && ticketId) {
        const res  = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t    = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.miete_alt) Object.assign(form.miete_alt, desc.miete_alt)
        if (desc.miete_neu) Object.assign(form.miete_neu, desc.miete_neu)
        if (desc.it_alt)    Object.assign(form.it_alt,    desc.it_alt)
        if (desc.it_neu)    Object.assign(form.it_neu,    desc.it_neu)
        if (desc.marketing) Object.assign(form.marketing,  desc.marketing)
        if (desc.fuhrpark)  Object.assign(form.fuhrpark,   desc.fuhrpark)

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
    return JSON.stringify({
      miete_alt: form.miete_alt,
      miete_neu: form.miete_neu,
      it_alt:    form.it_alt,
      it_neu:    form.it_neu,
      marketing: form.marketing,
      fuhrpark:  form.fuhrpark,
    })
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
        ticket_type:      'niederlassung-umzug',
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
  if (!ticketId) return
  if (action === 'complete') {
    if (!validate()) return
    pendingComplete.value = true
    return
  }
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
    form, companies, loading, submitting,
    pendingConfirm, pendingComplete,
    validationTriggered, errors,
    init, validate, isInvalid, fieldClass,
    submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}