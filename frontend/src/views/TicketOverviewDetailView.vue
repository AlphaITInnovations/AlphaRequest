<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { client } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import TicketDetailBody from '@/components/tickets/TicketDetailBody.vue'

const route  = useRoute()
const router = useRouter()
const id     = Number(route.params.id)

const loading = ref(true)
const data    = ref<any>(null)

async function load() {
  try {
    const { data: res } = await client.get(`/overview/tickets/${id}`)
    data.value = res.data
  } catch {
    // Kein Zugriff / nicht gefunden → zurück zum Dashboard.
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <AppLayout title="Ticket-Übersicht">
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <div v-else-if="data" class="max-w-7xl mx-auto space-y-6">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-gray-400">Ticket #{{ data.id }}</p>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white mt-0.5">{{ data.title }}</h1>
        </div>
        <button @click="router.back()"
                class="px-4 py-2 rounded-xl border border-gray-200 dark:border-white/10
                       text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition">
          ← Zurück
        </button>
      </div>

      <TicketDetailBody :data="data" @reload="load" />
    </div>
  </AppLayout>
</template>
