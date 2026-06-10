<script setup lang="ts">
import { onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import BasisTicketForm from '@/components/tickets/BasisTicketForm.vue'
import { useBasisTicket } from '@/composables/useBasisTicket'

const ctx = useBasisTicket('create')

onMounted(() => {
  ctx.init()
})
</script>

<template>
  <AppLayout title="Neues Ticket">
    <BasisTicketForm :ctx="ctx" />
  </AppLayout>
</template>