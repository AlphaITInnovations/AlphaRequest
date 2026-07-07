<script setup lang="ts">
import { ref } from 'vue'
import { client } from '@/api/client'

// Aktions-Panel (kein Speicher-Status): sendet eine Testmail.
const mailTo      = ref('')
const mailLoading = ref(false)
const mailResult  = ref<{ ok: boolean; msg: string } | null>(null)

async function sendTestMail() {
  if (!mailTo.value.trim()) return
  mailLoading.value = true; mailResult.value = null
  try {
    const { data } = await client.post('/settings/test-mail', { to: mailTo.value.trim() })
    mailResult.value = { ok: true, msg: data.data.message }
  } catch (e: any) {
    mailResult.value = { ok: false, msg: e.response?.data?.detail ?? 'Fehler' }
  } finally { mailLoading.value = false }
}
</script>

<template>
  <section>
    <h2 class="section-title">Testmail</h2>
    <div class="card-section space-y-4">
      <div class="flex gap-3">
        <input v-model="mailTo" type="email" placeholder="empfaenger@firma.de" class="set-input flex-1" />
        <button @click="sendTestMail" :disabled="mailLoading" class="btn-primary disabled:opacity-60">
          {{ mailLoading ? 'Sende…' : 'Senden' }}
        </button>
      </div>
      <div v-if="mailResult" class="rounded-xl border px-4 py-3 text-sm"
           :class="mailResult.ok
             ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300/60 text-emerald-800 dark:text-emerald-200'
             : 'bg-red-50 dark:bg-red-900/20 border-red-300/60 text-red-800 dark:text-red-200'">
        {{ mailResult.msg }}
      </div>
    </div>
  </section>
</template>
