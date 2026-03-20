
<!-- ── NiederlassungUmzugEditView.vue ─────────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungUmzugForm from '@/components/tickets/NiederlassungUmzugForm.vue'
import { useNiederlassungUmzug } from '@/composables/useNiederlassungUmzug'

const route = useRoute()
const ctx   = useNiederlassungUmzug('edit', Number(route.params.id))
onMounted(() => ctx.init())
</script>

<template>
  <AppLayout title="Niederlassung umziehen – bearbeiten">
    <div v-if="ctx.loading.value" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <NiederlassungUmzugForm v-else :ctx="ctx" phase="edit" />
  </AppLayout>
</template>
