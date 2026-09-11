import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

// 编辑器排版实验（03 期 §7）：启动即读设备本地偏好补 class（防首帧闪烁）。
// 回退=设置弹窗选「标准」即摘 class，:root 原值自动恢复
try {
  if (localStorage.getItem('velluma:editor-typography') === 'large') {
    document.documentElement.classList.add('editor-type-large')
  }
} catch {}

createApp(App).use(router).mount('#app')
