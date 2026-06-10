<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import BasisTicketForm from '@/components/tickets/BasisTicketForm.vue'
import { useBasisTicket } from '@/composables/useBasisTicket'

const route = useRoute()
const id    = Number(route.params.id)
const ctx   = useBasisTicket('edit', id)

onMounted(() => {
  ctx.init()
})
</script>

<template>
  <AppLayout title="Ticket bearbeiten">
    <BasisTicketForm :ctx="ctx" />
  </AppLayout>
</template>