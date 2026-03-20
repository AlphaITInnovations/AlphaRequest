import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { companiesApi } from '@/api/companies'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'
export interface UserRef { id: string; name: string }

export interface ZugangSperrenForm {
  accountable: UserRef | null
  assignee:    UserRef | null
  priority:    TicketPriority
  comment:     string

  personal: {
    first_name:           string
    last_name:            string
    cost_center:          string
    contract_company:     string
    exit_date:            string
    severance_agreement:  string
  }

  it: {
    mail_forwarding:    string
    mail_forward_to:    string
    mailbox_access:     string
    mailbox_access_for: string
    auto_reply:         string
    auto_reply_text:    string
  }

  fuhrpark: {
    car:             string
    car_return_date: string
  }
}

// ── Validation ────────────────────────────────────────────────────────────────

type Rule = {
  required?: boolean
  requiredIf?: (form: ZugangSperrenForm) => boolean
}

const RULES_CREATE: Record<string, Rule> = {
  'personal.first_name':          { required: true },
  'personal.last_name':           { required: true },
  'personal.cost_center':         { required: true },
  'personal.contract_company':    { required: true },
  'personal.exit_date':           { required: true },
  'personal.severance_agreement': { required: true },
  'it.mail_forward_to':           { requiredIf: f => f.it.mail_forwarding === 'Ja' },
  'it.mailbox_access_for':        { requiredIf: f => f.it.mailbox_access === 'Ja' },
  'it.auto_reply_text':           { requiredIf: f => f.it.auto_reply === 'Ja' },
  'fuhrpark.car_return_date':     { requiredIf: f => f.fuhrpark.car === 'Ja' },
  'accountable':                  { required: true },
}

const RULES_EDIT: Record<string, Rule> = {
  ...RULES_CREATE,
  'it.mail_forwarding': { required: true },
  'it.mailbox_access':  { required: true },
  'it.auto_reply':      { required: true },
  'fuhrpark.car':       { required: true },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useZugangSperren(phase: Phase, ticketId?: number) {
  const router              = useRouter()
  const companies           = ref<string[]>([])
  const loading             = ref(false)
  const submitting          = ref(false)
  const validationTriggered = ref(false)
  const errors              = ref<string[]>([])
  const pendingConfirm      = ref(false)
  const pendingComplete     = ref(false)

  const form = reactive<ZugangSperrenForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    personal: {
      first_name: '', last_name: '', cost_center: '',
      contract_company: '', exit_date: '', severance_agreement: '',
    },
    it: {
      mail_forwarding: '', mail_forward_to: '',
      mailbox_access: '', mailbox_access_for: '',
      auto_reply: '', auto_reply_text: '',
    },
    fuhrpark: { car: '', car_return_date: '' },
  })

  const rules = phase === 'create' ? RULES_CREATE : RULES_EDIT

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === ''
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

        if (desc.personal) Object.assign(form.personal, desc.personal)
        if (desc.it)       Object.assign(form.it,       desc.it)
        if (desc.fuhrpark) Object.assign(form.fuhrpark,  desc.fuhrpark)

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
      personal: form.personal,
      it:       form.it,
      fuhrpark: form.fuhrpark,
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
        ticket_type:      'zugang-sperren',
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
    form, companies, loading, submitting,
    pendingConfirm, pendingComplete,
    validationTriggered, errors,
    init, validate, isInvalid, fieldClass,
    submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}