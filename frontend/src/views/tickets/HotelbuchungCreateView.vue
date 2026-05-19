<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import HotelbuchungForm from '@/components/tickets/HotelbuchungForm.vue'
import { useHotelbuchung } from '@/composables/useHotelbuchung'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useHotelbuchung()

onMounted(() => {
  if (!auth.canCreateTicket('hotelbuchung')) {
    router.replace('/dashboard')
    return
  }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Hotelbuchung (Dienstreise)">
    <HotelbuchungForm :ctx="ctx" />
  </AppLayout>
</template>