import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { initApi } from './composables/useApi'

initApi().then(() => {
  createApp(App).mount('#app')
})
