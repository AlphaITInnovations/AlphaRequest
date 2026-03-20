
<!-- ── NiederlassungSchliessenEditView.vue ────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungSchliessenForm from '@/components/tickets/NiederlassungSchliessenForm.vue'
import { useNiederlassungSchliessen } from '@/composables/useNiederlassungSchliessen'

const route = useRoute()
const ctx   = useNiederlassungSchliessen('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Niederlassung schließen – bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <NiederlassungSchliessenForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>