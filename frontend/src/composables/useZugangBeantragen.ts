import { ref, computed, reactive, watch } from 'vue'
import { client } from '@/api/client'
import { companiesApi } from '@/api/companies'
import { personalnummerApi } from '@/api/personalnummer'
import { useRouter } from 'vue-router'
import type { TicketPriority } from '@/types/ticket'

// ── Typen ──────────────────────────────────────────────────────────────────────

export type Phase = 'create' | 'edit'

export interface UserRef { id: string; name: string }

export interface GroupOption { id: string; name: string }

export interface ZugangForm {
  // Details (rechte Sidebar)
  accountable:  UserRef | null
  assignee:     UserRef | null
  priority:     TicketPriority
  comment:      string

  // Stammdaten
  personal: {
    first_name:        string
    last_name:         string
    title:             string
    private_street:    string
    private_zip:       string
    private_city:      string
    start_date:        string
    homeoffice:        string
    weekly_hours:      string
    federal_state:     string
    department:        string
    department_other:  string
    cost_center:       string
    location:          string
    contract_company:  string
    personal_number:   string
    supervisor_hr_id:   string
    supervisor_hr_name: string
    contact_person_id:   string
    contact_person_name: string
  }

  // IT
  it: {
    appearance_company: string
    signature: {
      title:  string
      street: string
      zip:    string
      city:   string
    }
    timebutler: {
      vacation_year:  string
      supervisor_id:   string
      supervisor_name: string
    }
    software: {
      datev:        boolean
      datev_rights: string
      persopro:     boolean
      timejob:      boolean
      zvoove:        boolean
    }
    phone_order: {
      enabled:  boolean
      location: string
    }
    other_systems: string
    mailboxes: {
      info_mailbox: boolean
      additional:   string
      notes:        string
    }
    additional_cost_centers: string
  }

  // Fuhrpark
  fuhrpark: {
    car:       string
    car_class: string
    car_from:  string
  }
}

// ── Validierungsregeln ────────────────────────────────────────────────────────

type Rule = {
  required?: boolean
  pattern?: RegExp
  requiredIf?: (form: ZugangForm) => boolean
}

const RULES_CREATE: Record<string, Rule> = {
  'personal.first_name':       { required: true },
  'personal.last_name':        { required: true },
  'personal.title':            { required: true },
  'personal.private_street':   { required: true },
  'personal.private_zip':      { required: true, pattern: /^[0-9]{5}$/ },
  'personal.private_city':     { required: true },
  'personal.start_date':       { required: true },
  'personal.homeoffice':       { required: true },
  'personal.weekly_hours':     { required: true },
  'personal.federal_state':    { required: true },
  'personal.department':       { required: true },
  'personal.department_other': { requiredIf: f => f.personal.department === 'Sonstige' },
  'personal.cost_center':      { required: true },
  'personal.location':         { required: true },
  'personal.contract_company': { required: true },
  'personal.personal_number':  { required: true },
  'personal.supervisor_hr_id': { required: true },
  'personal.contact_person_id':{ required: true },
  'it.timebutler.vacation_year':  { required: true },
  'it.timebutler.supervisor_id':  { required: true },
  'fuhrpark.car':               { required: true },
  'fuhrpark.car_class':         { requiredIf: f => f.fuhrpark.car === 'Ja' },
  'fuhrpark.car_from':          { requiredIf: f => f.fuhrpark.car === 'Ja' },
  'accountable':                { required: true },
}

const RULES_EDIT: Record<string, Rule> = {
  ...RULES_CREATE,
  'it.appearance_company':    { required: true },
  'it.signature.title':       { required: true },
  'it.signature.street':      { required: true },
  'it.signature.zip':         { required: true, pattern: /^[0-9]{5}$/ },
  'it.signature.city':        { required: true },
  'it.mailboxes.notes':       { requiredIf: f => f.it.mailboxes.additional === 'Ja' },
}

// ── Hilfsfunktion: tief lesen ─────────────────────────────────────────────────

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useZugangBeantragen(phase: Phase, ticketId?: number) {
  const router = useRouter()

  const companies       = ref<string[]>([])
  const departments     = ref<GroupOption[]>([])
  const loading         = ref(false)
  const submitting      = ref(false)
  const validationTriggered = ref(false)
  const errors          = ref<string[]>([])

  const form = reactive<ZugangForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    personal: {
      first_name: '', last_name: '', title: '',
      private_street: '', private_zip: '', private_city: '',
      start_date: '', homeoffice: '', weekly_hours: '', federal_state: '',
      department: '', department_other: '',
      cost_center: '', location: '', contract_company: '',
      personal_number: '', supervisor_hr_id: '', supervisor_hr_name: '',
      contact_person_id: '', contact_person_name: '',
    },

    it: {
      appearance_company: '',
      signature: { title: '', street: '', zip: '', city: '' },
      timebutler: { vacation_year: '', supervisor_id: '', supervisor_name: '' },
      software: { datev: false, datev_rights: '', persopro: false, timejob: false, zvoove: false },
      phone_order: { enabled: false, location: '' },
      other_systems: '',
      mailboxes: { info_mailbox: true, additional: '', notes: '' },
      additional_cost_centers: '',
    },

    fuhrpark: { car: '', car_class: '', car_from: '' },
  })

  // ── Auto-fill signature title from personal title ───────────────────────────
  // Track whether the user has manually edited the signature title
  const signatureTitleManuallyEdited = ref(false)

  watch(() => form.personal.title, (newVal) => {
    if (!signatureTitleManuallyEdited.value) {
      form.it.signature.title = newVal
    }
  })

  function onSignatureTitleInput() {
    signatureTitleManuallyEdited.value = true
  }

  // ── Validation ──────────────────────────────────────────────────────────────

  const rules = computed(() => phase === 'create' ? RULES_CREATE : RULES_EDIT)

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === ''
  }

  function isInvalid(path: string): boolean {
    const rule = rules.value[path]
    if (!rule) return false

    const value = path === 'accountable'
      ? form.accountable?.id
      : getDeep(form as unknown as Record<string, unknown>, path)

    // Department: "Keine" counts as valid (no value passed)
    if (path === 'personal.department' && form.personal.department === 'Keine') return false

    if (rule.requiredIf) return rule.requiredIf(form) && isEmpty(value)
    if (rule.required && isEmpty(value)) return true
    if (rule.pattern && !isEmpty(value) && !rule.pattern.test(String(value))) return true
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
    const failed = Object.keys(rules.value).filter(p => isInvalid(p))
    errors.value = failed

    if (failed.length > 0) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return false
    }

    return true
  }

  // ── Load data ───────────────────────────────────────────────────────────────

  async function init() {
    loading.value = true
    try {
      // Load companies
      const { data: compData } = await companiesApi.list()
      companies.value = compData.data.companies

      // Load department groups from API
      try {
        const { data: groupsData } = await client.get<{ data: GroupOption[] }>('/settings/groups')
        departments.value = groupsData.data
      } catch {
        departments.value = []
      }

      if (phase === 'edit' && ticketId) {
        const res = await client.get<{ data: { description: string; priority: string; comment: string; assignee_id: string; assignee_name: string; accountable_id: string; accountable_name: string } }>(`/tickets/${ticketId}`)
        const t = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.personal) Object.assign(form.personal, desc.personal)

        // Legacy migration: old private_address → new fields
        if (desc.personal?.private_address && !desc.personal?.private_street) {
          form.personal.private_street = desc.personal.private_address
        }

        if (desc.it) {
          if (desc.it.appearance_company != null) form.it.appearance_company = desc.it.appearance_company
          // Legacy: migrate from old allgemein section
          if (desc.allgemein?.appearance_company && !desc.it.appearance_company) {
            form.it.appearance_company = desc.allgemein.appearance_company
          }
          if (desc.it.signature)    Object.assign(form.it.signature,    desc.it.signature)
          if (desc.it.software)     Object.assign(form.it.software,     desc.it.software)
          if (desc.it.phone_order)  Object.assign(form.it.phone_order,  desc.it.phone_order)
          if (desc.it.timebutler)   Object.assign(form.it.timebutler,   desc.it.timebutler)
          if (desc.it.mailboxes)    Object.assign(form.it.mailboxes,    desc.it.mailboxes)
          if (desc.it.other_systems != null)          form.it.other_systems = desc.it.other_systems
          if (desc.it.additional_cost_centers != null) form.it.additional_cost_centers = desc.it.additional_cost_centers
        }
        if (desc.fuhrpark) Object.assign(form.fuhrpark, desc.fuhrpark)

        form.priority    = t.priority as TicketPriority
        form.comment     = t.comment ?? ''
        form.assignee    = t.assignee_id    ? { id: t.assignee_id,    name: t.assignee_name }    : null
        form.accountable = t.accountable_id ? { id: t.accountable_id, name: t.accountable_name } : null

        // Mark signature title as manually edited if it differs from personal title
        if (form.it.signature.title && form.it.signature.title !== form.personal.title) {
          signatureTitleManuallyEdited.value = true
        }
      }
    } finally {
      loading.value = false
    }
  }

  // ── Personalnummer ──────────────────────────────────────────────────────────

  async function generatePersonalnummer() {
    if (form.personal.personal_number) return
    try {
      const { data } = await personalnummerApi.next()
      form.personal.personal_number = String(data.data.personalnummer)
    } catch {
      alert('Fehler beim Generieren der Personalnummer')
    }
  }

  // ── Submit ──────────────────────────────────────────────────────────────────

  function buildDescription(): string {
    const personal = { ...form.personal }
    // If department is "Keine", send empty string
    if (personal.department === 'Keine') {
      personal.department = ''
      personal.department_other = ''
    }
    // If department is not "Sonstige", clear department_other
    if (personal.department !== 'Sonstige') {
      personal.department_other = ''
    }

    return JSON.stringify({
      personal,
      it: form.it,
      fuhrpark: form.fuhrpark,
    })
  }

  const pendingConfirm  = ref(false)
  const pendingComplete = ref(false)

  async function submitCreate() {
    if (!validate()) return
    if (!form.accountable) return
    pendingConfirm.value = true
  }

  async function confirmCreate() {
    if (!form.accountable) return
    submitting.value = true
    pendingConfirm.value = false
    try {
      await client.post('/tickets', {
        ticket_type:      'zugang-beantragen',
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
      if (action === 'complete') {
        await client.post(`/tickets/${ticketId}/submit`)
      }
      router.push('/dashboard')
    } catch {
      alert('Fehler beim Speichern')
    } finally {
      submitting.value = false
    }
  }

  return {
    form, companies, departments, loading, submitting, pendingConfirm, pendingComplete,
    validationTriggered, errors,
    init, validate, isInvalid, fieldClass, onSignatureTitleInput,
    generatePersonalnummer, submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}