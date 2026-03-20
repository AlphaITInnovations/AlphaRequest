
<!-- ── ZugangCreateView.vue ─────────────────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import ZugangBeantragenForm from '@/components/tickets/ZugangBeantragenForm.vue'
import { useZugangBeantragen } from '@/composables/useZugangBeantragen'

const ctx = useZugangBeantragen('create')
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Onboarding Mitarbeiter:in">
    <ZugangBeantragenForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>