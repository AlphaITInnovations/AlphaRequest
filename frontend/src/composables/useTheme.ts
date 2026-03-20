import { ref, watchEffect } from 'vue'

// Default: light – nur dark wenn explizit gesetzt
const dark = ref(localStorage.getItem('theme') === 'dark')

watchEffect(() => {
  document.documentElement.classList.toggle('dark', dark.value)
})

export function useTheme() {
  function toggleDark() {
    dark.value = !dark.value
    localStorage.setItem('theme', dark.value ? 'dark' : 'light')
  }

  return { dark, toggleDark }
}