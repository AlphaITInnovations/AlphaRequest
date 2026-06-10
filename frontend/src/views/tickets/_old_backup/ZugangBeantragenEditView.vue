<!-- ── ZugangBeantragenEditView.vue ───────────────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import ZugangBeantragenForm from '@/components/tickets/ZugangBeantragenForm.vue'
import { useZugangBeantragen } from '@/composables/useZugangBeantragen'

const route = useRoute()
const ticketId = Number(route.params.id)
const ctx = useZugangBeantragen('edit', ticketId)
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Onboarding bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>
    <ZugangBeantragenForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>