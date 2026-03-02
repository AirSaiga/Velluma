import { ref, onMounted } from 'vue'
import { configApi } from './useApi'

export type ThemeType = 'light' | 'dark'

const theme = ref<ThemeType>('light')

export function useTheme() {
  const setTheme = async (newTheme: ThemeType) => {
    theme.value = newTheme

    // 更新 document class
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }

    // 持久化到后端
    try {
      await configApi.update({ theme: newTheme })
    } catch (error) {
      console.error('保存主题配置失败:', error)
    }
  }

  const initTheme = async () => {
    try {
      const config = await configApi.get() as { theme?: ThemeType }
      if (config.theme) {
        setTheme(config.theme)
      }
    } catch (error) {
      console.error('加载主题配置失败:', error)
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
