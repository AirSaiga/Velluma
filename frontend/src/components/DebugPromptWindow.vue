<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { readStoredPromptData, subscribePromptData } from '../composables/useApi'

const systemPrompt = ref('')
const userPrompt = ref('')
const currentPrompt = ref(null)
let unsubscribePromptChannel = null

function handlePrompt(data) {
  if (!data || typeof data !== 'object') return
  const nextSystemPrompt = typeof data.system_prompt === 'string' ? data.system_prompt : ''
  const nextUserPrompt = typeof data.user_prompt === 'string' ? data.user_prompt : ''
  if (!nextSystemPrompt && !nextUserPrompt) return
  currentPrompt.value = {
    system_prompt: nextSystemPrompt,
    user_prompt: nextUserPrompt
  }
  systemPrompt.value = nextSystemPrompt
  userPrompt.value = nextUserPrompt
}

function handleStorageChange(event) {
  if (event.key !== 'velluma_last_prompt' || !event.newValue) return
  try {
    handlePrompt(JSON.parse(event.newValue))
  } catch (e) {
    console.warn('解析 storage prompt 失败', e)
  }
}

function clearPrompt() {
  currentPrompt.value = null
  systemPrompt.value = ''
  userPrompt.value = ''
}

onMounted(() => {
  const storedPrompt = readStoredPromptData()
  if (storedPrompt) {
    handlePrompt(storedPrompt)
  }
  unsubscribePromptChannel = subscribePromptData(handlePrompt)
  window.addEventListener('storage', handleStorageChange)
  if (window.electronAPI) {
    window.electronAPI.on('prompt-data', handlePrompt)
  }
})

onUnmounted(() => {
  if (unsubscribePromptChannel) {
    unsubscribePromptChannel()
    unsubscribePromptChannel = null
  }
  window.removeEventListener('storage', handleStorageChange)
  if (window.electronAPI) {
    window.electronAPI.removeListener('prompt-data', handlePrompt)
  }
})
</script>

<template>
  <div class="debug-window">
    <div class="header">
      <h1>Prompt Debug</h1>
      <button @click="clearPrompt" class="clear-btn">Clear</button>
    </div>
    
    <div class="prompt-section" v-if="currentPrompt">
      <div class="section">
        <h2>System Prompt</h2>
        <pre class="prompt-content">{{ systemPrompt }}</pre>
      </div>
      
      <div class="section">
        <h2>User Prompt</h2>
        <pre class="prompt-content">{{ userPrompt }}</pre>
      </div>
    </div>
    
    <div class="empty-state" v-else>
      <p>Waiting for prompt data...</p>
      <p class="hint">Generate a chapter to see the prompt here.</p>
    </div>
  </div>
</template>

<style scoped>
.debug-window {
  height: 100vh;
  padding: 20px;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Consolas', 'Monaco', monospace;
  overflow: auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid #333;
}

.header h1 {
  margin: 0;
  font-size: 18px;
  color: #569cd6;
}

.clear-btn {
  padding: 6px 12px;
  background: #4a4a4a;
  color: #d4d4d4;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.clear-btn:hover {
  background: #5a5a5a;
}

.prompt-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section {
  background: #252526;
  border-radius: 6px;
  padding: 15px;
}

.section h2 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: #4ec9b0;
}

.prompt-content {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.5;
  max-height: 300px;
  overflow-y: auto;
  background: #1e1e1e;
  padding: 10px;
  border-radius: 4px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 50vh;
  color: #808080;
}

.empty-state p {
  margin: 5px 0;
}

.hint {
  font-size: 12px;
  color: #606060;
}
</style>
