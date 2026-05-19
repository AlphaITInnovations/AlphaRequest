import { ref, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { client } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { TicketPriority } from '@/types/ticket'

export type Phase = 'create' | 'edit'
export interface UserRef { id: string; name: string }

export interface HotelbuchungForm {
  priority: TicketPriority
  comment:  string

  buchung: {
    // Antragsteller
    antragsteller_name:  string
    antragsteller_email: string
    niederlassung:       string
    telefonnummer:       string
    kostenstelle:        string

    // Reisedaten
    anreisedatum:        string
    abreisedatum:        string
    anzahl_naechte:      string

    // Reiseziel
    ort_stadt:           string
    partner_hotel:       string
    hotelwunsch:         string

    // Reiseanlass
    reiseanlass:         string

    // Kundentermin-Details
    kunde_name:          string
    kunde_anschrift:     string
    kunde_grund:         string

    // Besuch Niederlassung
    besuch_niederlassung: string
    besuch_begruendung:   string

    // Sonstiges
    sonstiges_grund:     string

    // Genehmigung (Sonstiges)
    genehmigung_id:      string
    genehmigung_name:    string

    // Budgetvorgaben
    budget_bestaetigung: string  // 'unter_120' | 'abweichung'
    budget_begruendung:  string
    budget_genehmigung_id:   string
    budget_genehmigung_name: string

    // Besondere Anforderungen
    besondere_anforderungen: string
  }
}

type Rule = {
  required?: boolean
  requiredIf?: (f: HotelbuchungForm) => boolean
}

const RULES: Record<string, Rule> = {
  'buchung.antragsteller_name':   { required: true },
  'buchung.antragsteller_email':  { required: true },
  'buchung.telefonnummer':       { required: true },
  'buchung.niederlassung':        { required: true },
  'buchung.kostenstelle':         { required: true },
  'buchung.anreisedatum':         { required: true },
  'buchung.abreisedatum':         { required: true },
  'buchung.ort_stadt':            { required: true },
  'buchung.reiseanlass':          { required: true },

  // Kundentermin
  'buchung.kunde_name':           { requiredIf: f => f.buchung.reiseanlass === 'kundentermin' },
  'buchung.kunde_anschrift':      { requiredIf: f => f.buchung.reiseanlass === 'kundentermin' },
  'buchung.kunde_grund':          { requiredIf: f => f.buchung.reiseanlass === 'kundentermin' },

  // Besuch Niederlassung
  'buchung.besuch_niederlassung': { requiredIf: f => f.buchung.reiseanlass === 'besuch_niederlassung' },

  // Sonstiges
  'buchung.sonstiges_grund':      { requiredIf: f => f.buchung.reiseanlass === 'sonstiges' },
  'buchung.genehmigung_id':       { requiredIf: f => f.buchung.reiseanlass === 'sonstiges' },

  // Budgetvorgaben
  'buchung.budget_bestaetigung':      { required: true },
  'buchung.budget_begruendung':       { requiredIf: f => f.buchung.budget_bestaetigung === 'abweichung' },
  'buchung.budget_genehmigung_id':    { requiredIf: f => f.buchung.budget_bestaetigung === 'abweichung' },
}

function getDeep(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: unknown, k) => {
    if (o && typeof o === 'object') return (o as Record<string, unknown>)[k]
    return undefined
  }, obj as unknown)
}

export function useHotelbuchung(phase: Phase = 'create', ticketId?: number) {
  const router = useRouter()
  const auth   = useAuthStore()

  const loading             = ref(false)
  const submitting          = ref(false)
  const validationTriggered = ref(false)
  const errors              = ref<string[]>([])
  const pendingConfirm      = ref(false)
  const pendingComplete     = ref(false)

  const form = reactive<HotelbuchungForm>({
    priority: 'medium',
    comment:  '',

    buchung: {
      antragsteller_name:  '',
      antragsteller_email: '',
      niederlassung:       '',
      telefonnummer:       '',
      kostenstelle:        '',

      anreisedatum:        '',
      abreisedatum:        '',
      anzahl_naechte:      '',

      ort_stadt:           '',
      partner_hotel:       '',
      hotelwunsch:         '',

      reiseanlass:         '',

      kunde_name:          '',
      kunde_anschrift:     '',
      kunde_grund:         '',

      besuch_niederlassung: '',
      besuch_begruendung:   '',

      sonstiges_grund:     '',

      genehmigung_id:      '',
      genehmigung_name:    '',

      budget_bestaetigung: '',
      budget_begruendung:  '',
      budget_genehmigung_id:   '',
      budget_genehmigung_name: '',

      besondere_anforderungen: '',
    },
  })

  // ── Auto-Berechnung Übernachtungen ──────────────────────────────────────────
  const naechteManuallyEdited = ref(false)

  watch([() => form.buchung.anreisedatum, () => form.buchung.abreisedatum], ([anreise, abreise]) => {
    if (naechteManuallyEdited.value) return
    if (anreise && abreise) {
      const diff = Math.round((new Date(abreise).getTime() - new Date(anreise).getTime()) / (1000 * 60 * 60 * 24))
      form.buchung.anzahl_naechte = diff > 0 ? String(diff) : ''
    }
  })

  function onNaechteInput() {
    naechteManuallyEdited.value = true
  }

  function isEmpty(v: unknown): boolean {
    return v === null || v === undefined || v === ''
  }

  function isInvalid(path: string): boolean {
    const rule = RULES[path]
    if (!rule) return false
    const value = getDeep(form as unknown as Record<string, unknown>, path)
    const active = rule.required || (rule.requiredIf ? rule.requiredIf(form) : false)
    if (!active) return false
    return isEmpty(value)
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
        form.buchung.antragsteller_name  = name
        form.buchung.antragsteller_email = email
      }

      if (phase === 'edit' && ticketId) {
        const res = await client.get<{ data: any }>(`/tickets/${ticketId}`)
        const t   = res.data.data
        const desc = JSON.parse(t.description || '{}')

        if (desc.buchung) Object.assign(form.buchung, desc.buchung)
        form.priority = t.priority as TicketPriority
        form.comment  = t.comment ?? ''
      }
    } finally {
      loading.value = false
    }
  }

  function buildDescription(): string {
    return JSON.stringify({ buchung: form.buchung })
  }

  async function submitCreate() {
    if (!validate()) return
    pendingConfirm.value = true
  }

  async function confirmCreate() {
    submitting.value = true
    pendingConfirm.value = false
    try {
      await client.post('/tickets', {
        ticket_type:      'hotelbuchung',
        description:      buildDescription(),
        assignee_id:      'fachabteilung',
        assignee_name:    'fachabteilung',
        accountable_id:   'fachabteilung',
        accountable_name: 'fachabteilung',
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
        description: buildDescription(),
        priority:    form.priority,
        comment:     form.comment,
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
    form, loading, submitting, phase,
    pendingConfirm, pendingComplete,
    validationTriggered, errors,
    init, validate, isInvalid, fieldClass, onNaechteInput,
    submitCreate, confirmCreate, submitEdit, confirmComplete,
  }
}