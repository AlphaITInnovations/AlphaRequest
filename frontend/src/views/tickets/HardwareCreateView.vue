
<!-- ── HardwareCreateView.vue ──────────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import HardwareForm from '@/components/tickets/HardwareForm.vue'
import { useHardware } from '@/composables/useHardware'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useHardware('create')

onMounted(() => {
  if (!auth.canCreateTicket('hardware')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Hardwarebestellung">
    <HardwareForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>