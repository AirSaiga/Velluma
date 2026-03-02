import { ref, onMounted } from 'vue'

const theme = ref('light')

export function useTheme() {
  const setTheme = (newTheme) => {
    theme.value = newTheme

    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }

    localStorage.setItem('velluma_theme', newTheme)
  }

  const initTheme = () => {
    const savedTheme = localStorage.getItem('velluma_theme')
    if (savedTheme) {
      setTheme(savedTheme)
    } else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      setTheme(prefersDark ? 'dark' : 'light')
    }
  }

  onMounted(() => {
    initTheme()
  })

  return {
    theme,
    setTheme,
    initTheme
  }
}
