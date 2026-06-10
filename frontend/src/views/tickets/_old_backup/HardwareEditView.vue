<!-- ── HardwareEditView.vue ────────────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import HardwareForm from '@/components/tickets/HardwareForm.vue'
import { useHardware } from '@/composables/useHardware'

const route = useRoute()
const ctx   = useHardware('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Hardwarebestellung bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <HardwareForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>