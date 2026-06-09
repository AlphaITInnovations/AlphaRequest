import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'

export interface UserRef { id: string; name: string }

export interface Eintrag {
  text:        string
  author_id:   string
  author_name: string
  timestamp:   string
}

export interface BasisTicketForm {
  accountable: UserRef | null
  assignee:    UserRef | null
  priority:    TicketPriority
  comment:     string

  ticket: {
    titel:     string
    eintraege: Eintrag[]
  }
}

type Rule = {
  required?: boolean
}

const RULES_CREATE: Record<string, Rule> = {
  'accountable':    { required: true },
  'ticket.titel':   { required: true },
}

const RULES_EDIT: Record<string, Rule> = {
  'accountable':    { required: true },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

export function useBasisTicket(phase: Phase = 'create', ticketId?: number) {
  const router = useRouter()
  const auth   = useAuthStore()

  const loading             = ref(false)
  const submitting          = ref(false)
  const validationTriggered = ref(false)
  const errors              = ref<string[]>([])
  const pendingConfirm      = ref(false)
  const pendingComplete     = ref(false)

  // Neuer Eintrag (nur in edit)
  const newEntryText = ref('')

  const form = reactive<BasisTicketForm>({
    accountable: null,
    assignee:    null,
    priority:    'medium',
    comment:     '',

    ticket: {
      titel:     '',
      eintraege: [],
    },
  })

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
    const failed = Object.keys(rules.value).filter(p => isInvalid(p))

    // Create: erster Eintrag muss vorhanden sein
    if (phase === 'create' && form.ticket.eintraege.length === 0) {
      failed.push('ticket.beschreibung')
    }

    // Edit: neuer Eintrag muss Text haben wenn man abschließt
    // (wird nur bei complete geprüft, nicht bei save)

    errors.value = failed
    if (failed.length > 0) { window.scrollTo({ top: 0, behavior: 'smooth' }); return false }
    return true
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    loading.value = true
    try {
      if (phase === 'edit' && ticketId) {
        const res = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t   = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.ticket) {
          form.ticket.titel     = desc.ticket.titel ?? ''
          form.ticket.eintraege = desc.ticket.eintraege ?? []
        }

        form.priority    = t.priority as TicketPriority
        form.comment     = t.comment ?? ''
        form.assignee    = t.assignee_id    ? { id: t.assignee_id,    name: t.assignee_name }    : null
        form.accountable = t.accountable_id ? { id: t.accountable_id, name: t.accountable_name } : null
      }
    } finally {
      loading.value = false
    }
  }

  // ── Eintrag hinzufügen ────────────────────────────────────────────────────

  function addEintrag(text: string) {
    if (!text.trim()) return
    form.ticket.eintraege.push({
      text:        text.trim(),
      author_id:   auth.user?.id ?? '',
      author_name: auth.user?.displayName ?? '',
      timestamp:   new Date().toISOString(),
    })
  }

  // ── Description bauen ─────────────────────────────────────────────────────

  function buildDescription(): string {
    return JSON.stringify({ ticket: form.ticket })
  }

  // ── Create ────────────────────────────────────────────────────────────────

  async function submitCreate(beschreibung: string) {
    // Ersten Eintrag hinzufügen
    addEintrag(beschreibung)
    if (!validate()) {
      // Eintrag wieder entfernen wenn Validierung fehlschlägt
      if (form.ticket.eintraege.length > 0) form.ticket.eintraege.pop()
      return
    }
    pendingConfirm.value = true
  }

  async function confirmCreate() {
    if (!form.accountable) return
    submitting.value = true
    pendingConfirm.value = false
    try {
      await client.post('/tickets/basis', {
        title:            form.ticket.titel,
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

  // ── Edit ──────────────────────────────────────────────────────────────────

  async function submitEdit(action: 'save' | 'complete') {
    if (!ticketId) return

    // Neuen Eintrag vor dem Speichern hinzufügen (wenn vorhanden)
    if (newEntryText.value.trim()) {
      addEintrag(newEntryText.value)
      newEntryText.value = ''
    }

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
    form, phase, loading, submitting,
    pendingConfirm, pendingComplete,
    validationTriggered, errors,
    newEntryText,
    init, validate, isInvalid, fieldClass,
    addEintrag, submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}