<script setup lang="ts">
import { computed } from 'vue'
import { PanelContainer, PanelCard, PanelEmpty } from './panels'
import Icon from './Icon.vue'

interface Comment {
  type?: string
  exact_quote?: string
  suggestion: string
  reader_feeling?: string
}

interface CritiqueResult {
  overall_praise?: string
  comments?: Comment[]
}

const props = defineProps<{
  result: CritiqueResult | null
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'jump-to-critique', comment: Comment): void
  (e: 'close-critique'): void
  (e: 'close'): void
}>()

const hasContent = computed(() => {
  if (!props.result) return false
  return !!(props.result.overall_praise || (props.result.comments && props.result.comments.length > 0))
})

const typeColors: Record<string, string> = {
  '结构': 'bg-blue-50 text-blue-600',
  '节奏': 'bg-green-50 text-green-600',
  '人物': 'bg-purple-50 text-purple-600',
  '对话': 'bg-orange-50 text-orange-600',
  '描写': 'bg-pink-50 text-pink-600',
  '情节': 'bg-indigo-50 text-indigo-600',
  '逻辑': 'bg-red-50 text-red-600',
  '文笔': 'bg-teal-50 text-teal-600'
}

function getTypeClass(type?: string): string {
  if (!type) return 'bg-gray-50 text-gray-600'
  return typeColors[type] || 'bg-gray-50 text-gray-600'
}

function handleCommentClick(comment: Comment) {
  if (comment.exact_quote) {
    emit('jump-to-critique', comment)
  }
}

function handleClose() {
  emit('close')
}

function handleCloseCritique() {
  emit('close-critique')
}
</script>

<template>
  <PanelContainer
    title="主编指导"
    icon="light-bulb"
    description="AI 深度阅读后给出的专业建议"
    :closable="true"
    @close="handleClose"
  >
    <div class="critique-content">
      <!-- 加载中 -->
      <div v-if="loading && !result" class="loading-state">
        <div class="loading-illustration">
          <div class="loading-pulse">
            <Icon name="light-bulb" :size="32" />
          </div>
        </div>
        <h4>正在深度阅读您的章节...</h4>
        <p>AI 主编正在分析剧情逻辑、节奏与人物表现</p>
      </div>

      <!-- 有结果展示 -->
      <div v-else-if="hasContent" class="critique-results">
        <!-- 总体评价 -->
        <div v-if="result?.overall_praise" class="praise-section">
          <div class="section-header">
            <Icon name="star" :size="14" />
            <span>总体亮点</span>
          </div>
          <div class="praise-content">
            {{ result.overall_praise }}
          </div>
        </div>

        <!-- 详细评论列表 -->
        <div v-if="result?.comments && result.comments.length > 0" class="comments-section">
          <div class="section-header">
            <Icon name="chat-bubble-left-right" :size="14" />
            <span>详细建议 ({{ result.comments.length }})</span>
          </div>

          <div class="comments-list">
            <PanelCard
              v-for="(comment, index) in result.comments"
              :key="index"
              :clickable="!!comment.exact_quote"
              @click="handleCommentClick(comment)"
            >
              <template #default>
                <div class="comment-card">
                  <div class="comment-header">
                    <span class="comment-type" :class="getTypeClass(comment.type)">
                      {{ comment.type || '建议' }}
                    </span>
                    <span v-if="comment.reader_feeling" class="reader-feeling">
                      {{ comment.reader_feeling }}
                    </span>
                  </div>

                  <div v-if="comment.exact_quote" class="quote-section">
                    <span class="quote-label">原句</span>
                    <blockquote class="quote-text">"{{ comment.exact_quote }}"</blockquote>
                  </div>

                  <div class="suggestion-section">
                    <span class="suggestion-label">建议</span>
                    <p class="suggestion-text">{{ comment.suggestion }}</p>
                  </div>
                </div>
              </template>
            </PanelCard>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <PanelEmpty
        v-else
        icon="magnifying-glass"
        title="暂无指导意见"
        description="点击编辑器上方的「获取主编指导」按钮开始分析"
      />
    </div>

    <!-- 关闭指导按钮（当结果存在时显示） -->
    <template v-if="result" #footer>
      <button class="close-critique-btn" @click="handleCloseCritique">
        <Icon name="x-mark" :size="14" />
        关闭指导
      </button>
    </template>
  </PanelContainer>
</template>

<style scoped>
.critique-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.loading-illustration {
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(124, 106, 173, 0.1), rgba(124, 106, 173, 0.05));
  border-radius: 20px;
  margin-bottom: 20px;
}

.loading-pulse {
  color: var(--accent-500);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { 
    opacity: 1;
    transform: scale(1);
  }
  50% { 
    opacity: 0.7;
    transform: scale(1.05);
  }
}

.loading-state h4 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.loading-state p {
  font-size: 13px;
  color: var(--text-muted);
  max-width: 280px;
}

/* 结果展示 */
.critique-results {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* 总体评价 */
.praise-section {
  padding: 16px;
  background: linear-gradient(135deg, rgba(124, 106, 173, 0.08), rgba(124, 106, 173, 0.03));
  border: 1px solid rgba(124, 106, 173, 0.15);
  border-radius: 12px;
}

.praise-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-line;
}

/* 评论列表 */
.comments-section {
  display: flex;
  flex-direction: column;
}

.comments-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.comment-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.comment-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.comment-type {
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 6px;
}

.reader-feeling {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
}

.quote-section {
  padding: 10px 12px;
  background: #fef3c7;
  border-left: 3px solid #f59e0b;
  border-radius: 0 8px 8px 0;
}

.quote-label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: #d97706;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.quote-text {
  font-size: 12px;
  line-height: 1.5;
  color: #92400e;
  font-style: italic;
  margin: 0;
}

.suggestion-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggestion-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--accent-500);
  text-transform: uppercase;
}

.suggestion-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 0;
}

/* 关闭按钮 */
.close-critique-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-critique-btn:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fecaca;
}
</style>
