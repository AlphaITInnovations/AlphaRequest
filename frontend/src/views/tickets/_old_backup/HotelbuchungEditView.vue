<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import HotelbuchungForm from '@/components/tickets/HotelbuchungForm.vue'
import { useHotelbuchung } from '@/composables/useHotelbuchung'

const route  = useRoute()
const id     = Number(route.params.id)
const ctx    = useHotelbuchung('edit', id)

onMounted(() => {
  ctx.init()
})
</script>

<template>
  <AppLayout title="Hotelbuchung bearbeiten">
    <HotelbuchungForm :ctx="ctx" />
  </AppLayout>
</template>