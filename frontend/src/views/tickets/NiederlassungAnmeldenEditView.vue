
<!-- ── NiederlassungAnmeldenEditView.vue ──────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungAnmeldenForm from '@/components/tickets/NiederlassungAnmeldenForm.vue'
import { useNiederlassungAnmelden } from '@/composables/useNiederlassungAnmelden'

const route = useRoute()
const ctx   = useNiederlassungAnmelden('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Niederlassung anmelden – bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <NiederlassungAnmeldenForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>