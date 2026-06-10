
<!-- ── ZugangSperrenCreateView.vue ────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import ZugangSperrenForm from '@/components/tickets/ZugangSperrenForm.vue'
import { useZugangSperren } from '@/composables/useZugangSperren'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useZugangSperren('create')

onMounted(() => {
  if (!auth.canCreateTicket('zugang-sperren')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Offboarding Mitarbeiter:in">
    <ZugangSperrenForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>
