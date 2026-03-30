
<!-- ── MarketingStelleEditView.vue ────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import MarketingStelleForm from '@/components/tickets/MarketingStelleForm.vue'
import { useMarketingStelle } from '@/composables/useMarketingStelle'

const route = useRoute()
const ctx   = useMarketingStelle('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Stellenanzeige bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <MarketingStelleForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>
