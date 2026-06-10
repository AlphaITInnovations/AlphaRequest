
<!-- ── NiederlassungSchliessenCreateView.vue ──────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungSchliessenForm from '@/components/tickets/NiederlassungSchliessenForm.vue'
import { useNiederlassungSchliessen } from '@/composables/useNiederlassungSchliessen'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useNiederlassungSchliessen('create')

onMounted(() => {
  if (!auth.canCreateTicket('niederlassung-schliessen')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Niederlassung schließen">
    <NiederlassungSchliessenForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>