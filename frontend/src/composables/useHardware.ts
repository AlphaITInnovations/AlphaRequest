import { ref, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { companiesApi } from '@/api/companies'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'
export interface UserRef { id: string; name: string }

export interface HardwareForm {
  accountable:  UserRef | null
  assignee:     UserRef | null
  priority:     TicketPriority
  comment:      string

  hardware: {
    mitarbeiterTyp: string

    // Basisdaten
    vorname:        string
    nachname:       string
    kostenstelle:   string
    firma:          string
    addr_strasse:   string
    addr_nr:        string
    addr_plz:       string
    addr_stadt:     string
    addr_tuerschild: string
    lieferungBis:   string

    // Hardware
    monitor:        { benoetigt: boolean; anzahl: number }
    geraet:         string
    artikel: {
      Notebook:        boolean
      MiniPC:          boolean
      Dockingstation:  boolean
      MausUndTastatur: boolean
      Headset:         boolean
      Webcam:          boolean
      Handy:           boolean
      SIM:             boolean
    }
    dockingVorhanden: boolean
    bemerkung:        string
    grundBestellung:  string
  }
}

// ── Validation ────────────────────────────────────────────────────────────────

type Rule = {
  required?: boolean
  requiredIf?: (form: HardwareForm) => boolean
  pattern?: RegExp
}

const RULES: Record<string, Rule> = {
  'hardware.mitarbeiterTyp': { required: true },
  'hardware.vorname':        { required: true },
  'hardware.nachname':       { required: true },
  'hardware.kostenstelle':   { required: true },
  'hardware.firma':          { required: true },
  'hardware.addr_strasse':   { required: true },
  'hardware.addr_nr':        { required: true },
  'hardware.addr_plz':       { required: true },
  'hardware.addr_stadt':     { required: true },
  'hardware.lieferungBis':   { required: true },
  'hardware.grundBestellung':{ requiredIf: f => f.hardware.mitarbeiterTyp === 'Bestandsmitarbeiter' },
  'accountable':             { required: true },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useHardware(phase: Phase, ticketId?: number) {
  const router  = useRouter()
  const companies       = ref<string[]>([])
  const loading         = ref(false)
  const submitting      = ref(false)
  const validationTriggered = ref(false)
  const errors          = ref<string[]>([])
  const pendingConfirm  = ref(false)
  const pendingComplete = ref(false)

  const form = reactive<HardwareForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    hardware: {
      mitarbeiterTyp:  '',
      vorname:         '',
      nachname:        '',
      kostenstelle:    '',
      firma:           '',
      addr_strasse:    '',
      addr_nr:         '',
      addr_plz:        '',
      addr_stadt:      '',
      addr_tuerschild: '',
      lieferungBis:    '',
      monitor:         { benoetigt: false, anzahl: 1 },
      geraet:          '',
      artikel: {
        Notebook: false, MiniPC: false, Dockingstation: false,
        MausUndTastatur: false, Headset: false, Webcam: false,
        Handy: false, SIM: false,
      },
      dockingVorhanden: false,
      bemerkung:        '',
      grundBestellung:  '',
    },
  })

  // ── Validation ──────────────────────────────────────────────────────────────

  function hasAnyHardware(): boolean {
    return Object.values(form.hardware.artikel).some(Boolean) || form.hardware.monitor.benoetigt
  }

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === ''
  }

  function isInvalid(path: string): boolean {
    const rule = RULES[path]
    if (!rule) return false
    const value = path === 'accountable'
      ? form.accountable?.id
      : getDeep(form as unknown as Record<string, unknown>, path)
    if (rule.requiredIf) return rule.requiredIf(form) && isEmpty(value)
    if (rule.required && isEmpty(value)) return true
    if (rule.pattern && !isEmpty(value) && !rule.pattern.test(String(value))) return true
    return false
  }

  // Hardware-Auswahl ist ein Sonderfall (mind. 1 Artikel oder Monitor)
  const hardwareInvalid = computed(() =>
    validationTriggered.value && !hasAnyHardware()
  )

  function fieldClass(path: string): string {
    const base = 'w-full rounded-xl border px-3.5 py-2.5 text-sm transition focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 focus:border-[#3EAAB8]/50 bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500'
    const err  = 'border-red-400 bg-red-50 dark:bg-red-900/20'
    const ok   = 'border-gray-200 dark:border-white/10'
    return `${base} ${validationTriggered.value && isInvalid(path) ? err : ok}`
  }

  function validate(): boolean {
    validationTriggered.value = true
    const failed = Object.keys(RULES).filter(p => isInvalid(p))
    if (!hasAnyHardware()) failed.push('hardware.artikel')
    errors.value = failed
    if (failed.length > 0) { window.scrollTo({ top: 0, behavior: 'smooth' }); return false }
    return true
  }

  function resetHardware() {
    form.hardware.monitor        = { benoetigt: false, anzahl: 1 }
    form.hardware.geraet         = ''
    form.hardware.artikel        = { Notebook: false, MiniPC: false, Dockingstation: false, MausUndTastatur: false, Headset: false, Webcam: false, Handy: false, SIM: false }
    form.hardware.dockingVorhanden = false
    form.hardware.bemerkung      = ''
    form.hardware.grundBestellung = ''
  }

  // ── Init ────────────────────────────────────────────────────────────────────

  async function init() {
    loading.value = true
    try {
      const { data } = await companiesApi.list()
      companies.value = data.data.companies

      if (phase === 'edit' && ticketId) {
        const res = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t   = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.hardware) Object.assign(form.hardware, desc.hardware)
        form.priority    = t.priority as TicketPriority
        form.comment     = t.comment ?? ''
        form.assignee    = t.assignee_id    ? { id: t.assignee_id,    name: t.assignee_name }    : null
        form.accountable = t.accountable_id ? { id: t.accountable_id, name: t.accountable_name } : null
      }
    } finally {
      loading.value = false
    }
  }

  // ── Submit ──────────────────────────────────────────────────────────────────

  function buildDescription(): string {
    return JSON.stringify({ hardware: form.hardware })
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
        ticket_type:      'hardware',
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
    validationTriggered, errors, hardwareInvalid,
    init, validate, isInvalid, fieldClass, resetHardware,
    submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}