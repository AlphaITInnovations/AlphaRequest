
<!-- ── NiederlassungUmzugCreateView.vue ───────────────────────────────────── -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppLayout from '@/components/AppLayout.vue'
import NiederlassungUmzugForm from '@/components/tickets/NiederlassungUmzugForm.vue'
import { useNiederlassungUmzug } from '@/composables/useNiederlassungUmzug'

const router = useRouter()
const auth   = useAuthStore()
const ctx    = useNiederlassungUmzug('create')

onMounted(() => {
  if (!auth.canCreateTicket('niederlassung-umzug')) { router.replace('/dashboard'); return }
  ctx.init()
})
</script>

<template>
  <AppLayout title="Niederlassung umziehen">
    <NiederlassungUmzugForm :ctx="ctx" phase="create" />
  </AppLayout>
</template>
