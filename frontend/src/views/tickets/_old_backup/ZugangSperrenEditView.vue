
<!-- ── ZugangSperrenEditView.vue ──────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import ZugangSperrenForm from '@/components/tickets/ZugangSperrenForm.vue'
import { useZugangSperren } from '@/composables/useZugangSperren'

const route = useRoute()
const ctx   = useZugangSperren('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Offboarding bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <ZugangSperrenForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>