import { defineAsyncComponent } from 'vue'
import { useZugangBeantragen }       from '@/composables/useZugangBeantragen'
import { useZugangSperren }          from '@/composables/useZugangSperren'
import { useHardware }               from '@/composables/useHardware'
import { useNiederlassungAnmelden }  from '@/composables/useNiederlassungAnmelden'
import { useNiederlassungSchliessen } from '@/composables/useNiederlassungSchliessen'
import { useNiederlassungUmzug }     from '@/composables/useNiederlassungUmzug'
import { useMarketingStelle }        from '@/composables/useMarketingStelle'
import { useHotelbuchung }           from '@/composables/useHotelbuchung'
import { useBasisTicket }            from '@/composables/useBasisTicket'
import type { TicketType } from '@/types/ticket'

export type ComposablePhase = 'create' | 'edit'

export interface TicketRegistryEntry {
  label:         string
  form:          ReturnType<typeof defineAsyncComponent>
  panel:         ReturnType<typeof defineAsyncComponent>
  useComposable: (phase: ComposablePhase, ticketId?: number) => any
}

export const TICKET_REGISTRY: Record<TicketType, TicketRegistryEntry> = {
  'zugang-beantragen': {
    label: 'Onboarding Mitarbeiter:in',
    form:  defineAsyncComponent(() => import('@/components/tickets/ZugangBeantragenForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/ZugangBeantragenContentPanel.vue')),
    useComposable: useZugangBeantragen,
  },
  'zugang-sperren': {
    label: 'Offboarding Mitarbeiter:in',
    form:  defineAsyncComponent(() => import('@/components/tickets/ZugangSperrenForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/ZugangSperrenContentPanel.vue')),
    useComposable: useZugangSperren,
  },
  'hardware': {
    label: 'Hardware-Anfrage',
    form:  defineAsyncComponent(() => import('@/components/tickets/HardwareForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/HardwareContentPanel.vue')),
    useComposable: useHardware,
  },
  'niederlassung-anmelden': {
    label: 'Niederlassung anmelden',
    form:  defineAsyncComponent(() => import('@/components/tickets/NiederlassungAnmeldenForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/NiederlassungAnmeldenContentPanel.vue')),
    useComposable: useNiederlassungAnmelden,
  },
  'niederlassung-schliessen': {
    label: 'Niederlassung schließen',
    form:  defineAsyncComponent(() => import('@/components/tickets/NiederlassungSchliessenForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/NiederlassungSchliessenContentPanel.vue')),
    useComposable: useNiederlassungSchliessen,
  },
  'niederlassung-umzug': {
    label: 'Niederlassung Umzug',
    form:  defineAsyncComponent(() => import('@/components/tickets/NiederlassungUmzugForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/NiederlassungUmzugContentPanel.vue')),
    useComposable: useNiederlassungUmzug,
  },
  'marketing-stellenanzeige': {
    label: 'Stellenanzeige',
    form:  defineAsyncComponent(() => import('@/components/tickets/MarketingStelleForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/MarketingStelleContentPanel.vue')),
    useComposable: useMarketingStelle,
  },
  'hotelbuchung': {
    label: 'Hotelbuchung',
    form:  defineAsyncComponent(() => import('@/components/tickets/HotelbuchungForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/HotelbuchungContentPanel.vue')),
    useComposable: useHotelbuchung,
  },
  'basis-ticket': {
    label: 'Basis-Ticket',
    form:  defineAsyncComponent(() => import('@/components/tickets/BasisTicketForm.vue')),
    panel: defineAsyncComponent(() => import('@/components/tickets/BasisTicketContentPanel.vue')),
    useComposable: useBasisTicket,
  },
}
