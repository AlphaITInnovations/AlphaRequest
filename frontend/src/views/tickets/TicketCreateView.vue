<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import { TICKET_REGISTRY } from '@/utils/ticketRegistry'
import type { TicketType } from '@/types/ticket'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()

const ticketType = route.params.type as TicketType
const entry      = TICKET_REGISTRY[ticketType]

// Composable must be called during setup (synchronous)
const ctx = entry?.useComposable('create')

onMounted(() => {
  if (!entry) { router.replace('/dashboard'); return }
  // Basis-Tickets darf jeder eingeloggte User erstellen (keine create_-Permission).
  // Für Prozess-Tickets greift die clientseitige Berechtigungsprüfung; der Server erzwingt sie ohnehin.
  if (ticketType !== 'basis-ticket' && !auth.canCreateTicket(ticketType)) {
    router.replace('/dashboard'); return
  }
  ctx.init()
})
</script>

<template>
  <AppLayout :title="entry?.label ?? 'Neues Ticket'">
    <div v-if="!entry" class="flex items-center justify-center py-24 text-gray-400">
      Unbekannter Ticket-Typ.
    </div>
    <component v-else :is="entry.form" :ctx="ctx" phase="create" />
  </AppLayout>
</template>
