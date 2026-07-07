import { ref } from 'vue'

// Singleton-Toast (module-level), damit Shell + Panels denselben Toast nutzen.
const toast = ref<{ msg: string; ok: boolean } | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

export function useToast() {
  function showToast(msg: string, ok = true) {
    toast.value = { msg, ok }
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { toast.value = null }, 3000)
  }
  return { toast, showToast }
}
