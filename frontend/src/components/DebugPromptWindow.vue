<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { readStoredPromptData, subscribePromptData } from '../services/api'

const promptHistory = ref([])
const currentPrompt = ref(null)
let unsubscribePromptChannel = null

function handlePrompt(data) {
  if (!data) return

  // Handle full debug history (array)
  if (Array.isArray(data)) {
    promptHistory.value = data
    currentPrompt.value = null
    return
  }
  
  // Handle single prompt object
  if (typeof data === 'object') {
    const nextSystemPrompt = typeof data.system_prompt === 'string' ? data.system_prompt : ''
    const nextUserPrompt = typeof data.user_prompt === 'string' ? data.user_prompt : ''
    
    if (nextSystemPrompt || nextUserPrompt) {
      currentPrompt.value = {
        system_prompt: nextSystemPrompt,
        user_prompt: nextUserPrompt
      }
      // Only clear history if we receive a single prompt that is NOT part of a history update
      // But typically history comes at the end. Real-time updates come during.
      // If we want to show "all at once", we prioritize history.
      // So if we have history, we might keep it until explicitly cleared or replaced by new history.
      // But if user starts new generation, we want to clear old history.
      // Usually "single prompt" events come from non-agentic generation or real-time agentic updates.
      // Real-time updates might be distracting if we just want the final report.
      // But the user asked for "after generation... print all".
      // So if we get an array, that's the final report.
      // If we get a single object, it might be a new generation starting.
      // Let's clear history if we get a single object, assuming it's a new stream.
      promptHistory.value = []
    }
  }
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
  promptHistory.value = []
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
    
    <!-- Full History View -->
    <div class="history-section" v-if="promptHistory.length > 0">
      <div v-for="(stage, index) in promptHistory" :key="index" class="stage-block">
        <h2 class="stage-title">
          {{ stage.stage }} 
          <span v-if="stage.iteration" class="iteration-tag">Iteration {{ stage.iteration }}</span>
        </h2>
        
        <!-- DRAFTING Stage with Beats -->
        <div v-if="stage.beat_prompts && stage.beat_prompts.length" class="beats-container">
          <div v-for="(beat, bIndex) in stage.beat_prompts" :key="bIndex" class="beat-block">
            <h3 class="beat-title">
              <span class="beat-idx">Beat {{ beat.beat_index }}</span>
              <span class="beat-stage">{{ beat.stage }}</span>
              <span v-if="beat.iteration" class="beat-iter">Iter {{ beat.iteration }}</span>
            </h3>
            <div class="prompt-pair">
              <div class="prompt-box">
                <h4>System</h4>
                <pre>{{ beat.system_prompt }}</pre>
              </div>
              <div class="prompt-box">
                <h4>User</h4>
                <pre>{{ beat.user_prompt }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- Standard Stage -->
        <div v-else class="prompt-pair">
          <div class="prompt-box">
            <h4>System</h4>
            <pre>{{ stage.system_prompt }}</pre>
          </div>
          <div class="prompt-box">
            <h4>User</h4>
            <pre>{{ stage.user_prompt }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Single Prompt View -->
    <div class="prompt-section" v-else-if="currentPrompt">
      <div class="section">
        <h2>System Prompt</h2>
        <pre class="prompt-content">{{ currentPrompt.system_prompt }}</pre>
      </div>
      
      <div class="section">
        <h2>User Prompt</h2>
        <pre class="prompt-content">{{ currentPrompt.user_prompt }}</pre>
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

/* History Styles */
.history-section {
  display: flex;
  flex-direction: column;
  gap: 30px;
}

.stage-block {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 15px;
  background: #252526;
}

.stage-title {
  margin: 0 0 15px 0;
  font-size: 16px;
  color: #569cd6;
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.iteration-tag {
  font-size: 12px;
  background: #0e639c;
  padding: 2px 6px;
  border-radius: 4px;
  color: white;
}

.beats-container {
  display: flex;
  flex-direction: column;
  gap: 15px;
  margin-left: 10px;
  border-left: 2px solid #333;
  padding-left: 15px;
}

.beat-block {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 10px;
}

.beat-title {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: #ce9178;
  display: flex;
  gap: 10px;
  align-items: center;
}

.beat-stage {
  color: #4ec9b0;
}

.beat-iter {
  font-size: 11px;
  background: #333;
  padding: 1px 4px;
  border-radius: 3px;
}

.prompt-pair {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prompt-box h4 {
  margin: 0 0 5px 0;
  font-size: 12px;
  color: #808080;
  text-transform: uppercase;
}

.prompt-box pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 12px;
  line-height: 1.5;
  max-height: 200px;
  overflow-y: auto;
  background: #000000;
  padding: 10px;
  border-radius: 4px;
  border: 1px solid #333;
  color: #cccccc;
}

/* Legacy Styles */
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
