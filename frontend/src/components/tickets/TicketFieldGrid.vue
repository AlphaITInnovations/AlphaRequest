<script setup lang="ts">
withDefaults(defineProps<{ cols?: 2 | 3 }>(), { cols: 2 })
</script>

<template>
  <div class="grid grid-cols-1 gap-4" :class="cols === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'">
    <slot />
  </div>
</template>
