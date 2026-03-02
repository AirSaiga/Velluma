<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  beats: {
    type: Array,
    default: () => []
  },
  entities: {
    type: Array,
    default: () => []
  },
  config: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['create', 'update', 'delete', 'generate', 'save-generated'])

const generatingBeatId = ref(null)
const generatingText = ref('')

const sortedBeats = computed(() => {
  return [...props.beats].sort((a, b) => a.order - b.order)
})

function addBeat() {
  const order = props.beats.length > 0 
    ? Math.max(...props.beats.map(b => b.order)) + 1 
    : 1
  emit('create', { order, instruction: '', entity_ids: [] })
}

function updateBeat(beat, updates) {
  emit('update', beat.id, { ...beat, ...updates })
}

function deleteBeat(beat) {
  if (confirm('确定要删除这个节拍吗？')) {
    emit('delete', beat.id)
  }
}

function moveBeat(beat, direction) {
  const currentOrder = beat.order
  const targetOrder = direction === 'up' ? currentOrder - 1 : currentOrder + 1
  
  const targetBeat = props.beats.find(b => b.order === targetOrder)
  if (targetBeat) {
    emit('update', beat.id, { order: targetOrder })
    emit('update', targetBeat.id, { order: currentOrder })
  }
}

function startGenerate(beat) {
  if (!props.config.api_key) {
    alert('请先在右侧面板配置 API Key')
    return
  }
  
  generatingBeatId.value = beat.id
  generatingText.value = ''
  
  emit('generate', beat, (chunk) => {
    generatingText.value += chunk
  }, () => {
    // 生成完成，保存结果
    emit('save-generated', beat.id, generatingText.value)
    generatingBeatId.value = null
    generatingText.value = ''
  }, (error) => {
    alert(`生成失败: ${error}`)
    generatingBeatId.value = null
    generatingText.value = ''
  })
}

function getEntityName(entityId) {
  const entity = props.entities.find(e => e.id === entityId)
  return entity?.name || entityId
}

function toggleEntity(beat, entityId) {
  const index = beat.entity_ids.indexOf(entityId)
  const newEntityIds = [...beat.entity_ids]
  
  if (index > -1) {
    newEntityIds.splice(index, 1)
  } else {
    newEntityIds.push(entityId)
  }
  
  updateBeat(beat, { entity_ids: newEntityIds })
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-primary)]">
    <!-- 头部 -->
    <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
      <h2 class="text-lg font-semibold text-[var(--text-primary)]">大纲编辑器</h2>
      <button
        @click="addBeat"
        class="px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded-lg transition-colors flex items-center gap-1"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        添加节拍
      </button>
    </div>
    
    <!-- 节拍列表 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <div
        v-for="beat in sortedBeats"
        :key="beat.id"
        class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] overflow-hidden"
      >
        <!-- 节拍头部 -->
        <div class="px-4 py-3 bg-[var(--bg-tertiary)]/50 border-b border-[var(--border-color)] flex items-center justify-between">
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium text-[var(--text-muted)]">#{{ beat.order }}</span>
            <div class="flex items-center gap-1">
              <button
                @click="moveBeat(beat, 'up')"
                :disabled="beat.order === 1"
                class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/>
                </svg>
              </button>
              <button
                @click="moveBeat(beat, 'down')"
                :disabled="beat.order === sortedBeats.length"
                class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
              </button>
            </div>
          </div>
          <button
            @click="deleteBeat(beat)"
            class="p-1.5 text-[var(--text-muted)] hover:text-rose-400 transition-colors"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>
        
        <!-- 节拍内容 -->
        <div class="p-4 space-y-4">
          <!-- 剧情指令输入 -->
          <div>
            <label class="block text-xs text-[var(--text-muted)] mb-1.5">剧情指令</label>
            <textarea
              :value="beat.instruction"
              @input="e => updateBeat(beat, { instruction: e.target.value })"
              rows="2"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
              placeholder="输入当前节拍的剧情指令..."
            />
          </div>
          
          <!-- 实体选择器 -->
          <div>
            <label class="block text-xs text-[var(--text-muted)] mb-1.5">涉及设定</label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="entity in entities"
                :key="entity.id"
                @click="toggleEntity(beat, entity.id)"
                class="px-2.5 py-1 text-xs rounded-full border transition-all"
                :class="beat.entity_ids.includes(entity.id) 
                  ? 'bg-primary-600/20 border-primary-500 text-primary-400' 
                  : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] text-[var(--text-muted)] hover:border-[var(--text-muted)]'"
              >
                {{ entity.name }}
              </button>
              <span v-if="entities.length === 0" class="text-xs text-[var(--text-muted)]">
                暂无可用设定，请先在左侧添加
              </span>
            </div>
          </div>
          
          <!-- 生成按钮 -->
          <div class="flex justify-end">
            <button
              @click="startGenerate(beat)"
              :disabled="generatingBeatId === beat.id || !beat.instruction.trim()"
              class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white text-sm rounded-lg transition-colors flex items-center gap-2"
            >
              <svg v-if="generatingBeatId === beat.id" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              {{ generatingBeatId === beat.id ? '生成中...' : '生成正文' }}
            </button>
          </div>
          
          <!-- 生成中的文本预览 -->
          <div v-if="generatingBeatId === beat.id && generatingText" class="p-3 bg-[var(--bg-tertiary)]/50 rounded-lg border border-[var(--border-color)]">
            <p class="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap typing-cursor">{{ generatingText }}</p>
          </div>
          
          <!-- 已生成的正文 -->
          <div v-if="beat.generated_text" class="p-3 bg-[var(--bg-tertiary)]/30 rounded-lg border border-[var(--border-color)]">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs text-[var(--text-muted)]">已生成正文</span>
              <button
                @click="updateBeat(beat, { generated_text: '' })"
                class="text-xs text-[var(--text-muted)] hover:text-rose-400 transition-colors"
              >
                清除
              </button>
            </div>
            <p class="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">{{ beat.generated_text }}</p>
          </div>
        </div>
      </div>
      
      <!-- 空状态 -->
      <div v-if="sortedBeats.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--bg-secondary)] flex items-center justify-center">
          <svg class="w-8 h-8 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
        </div>
        <p class="text-[var(--text-muted)] text-sm">暂无节拍，点击上方按钮添加</p>
      </div>
    </div>
  </div>
</template>
