
<!-- ── NiederlassungAnmeldenCreateView.vue ────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungAnmeldenForm from '@/components/tickets/NiederlassungAnmeldenForm.vue'
import { useNiederlassungAnmelden } from '@/composables/useNiederlassungAnmelden'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useNiederlassungAnmelden('create')

onMounted(() => {
  if (!auth.canCreateTicket('niederlassung-anmelden')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Niederlassung anmelden">
    <NiederlassungAnmeldenForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>