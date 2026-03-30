
<!-- ── MarketingStelleCreateView.vue ──────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import MarketingStelleForm from '@/components/tickets/MarketingStelleForm.vue'
import { useMarketingStelle } from '@/composables/useMarketingStelle'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useMarketingStelle('create')

onMounted(() => {
  if (!auth.canCreateTicket('marketing-stellenanzeige')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Marketing – Stellenanzeige">
    <MarketingStelleForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>
