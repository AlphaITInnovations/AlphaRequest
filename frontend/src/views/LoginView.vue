<script setup lang="ts">
const logoUrl = '/static/logo.png'

function startAuth() {
  window.location.href = '/start-auth'
}
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-white to-gray-100 dark:from-[#1E2327] dark:to-[#1E2327] flex items-center justify-center font-sans text-gray-900 dark:text-gray-100">
    <main class="bg-white dark:bg-[#2B3036] shadow-xl rounded-lg p-8 w-full max-w-md border border-gray-100 dark:border-gray-700">

      <img :src="logoUrl" alt="Firmenlogo" class="mx-auto mb-4 h-16 w-auto" loading="lazy" />

      <h1 class="text-2xl font-semibold text-center mb-6" style="color: #3EAAB8">
        AlphaRequest
      </h1>

      <p class="text-center text-sm text-gray-600 dark:text-gray-300 mb-6">
        Bitte melden Sie sich mit Ihrem Microsoft-Konto an...
      </p>

      <button
        @click="startAuth"
        class="block text-center w-full text-white font-medium py-2 rounded-md transition"
        style="background-color: #3EAAB8"
        onmouseover="this.style.backgroundColor='#2B7D89'"
        onmouseout="this.style.backgroundColor='#3EAAB8'"
      >
        Mit Microsoft anmelden
      </button>

      <p class="text-center text-xs text-gray-500 dark:text-gray-400 mt-6">
        © AlphaConsult Gruppe
      </p>
    </main>
  </div>
</template>