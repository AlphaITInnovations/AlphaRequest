<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import ZugangBeantragenForm from '@/components/tickets/ZugangBeantragenForm.vue'
import { useZugangBeantragen } from '@/composables/useZugangBeantragen'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useZugangBeantragen('create')

onMounted(() => {
  if (!auth.canCreateTicket('zugang-beantragen')) {
    router.replace('/dashboard')
    return
  }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Onboarding Mitarbeiter:in">
    <ZugangBeantragenForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>