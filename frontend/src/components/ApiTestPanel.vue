<script setup lang="ts">
import { ref } from 'vue'
import { systemApi } from '../services/api'
import { useToast } from '../composables/useToast'
import Icon from './Icon.vue'

const { showToast } = useToast()

const testing = ref(false)
const testResult = ref<{
  success: boolean
  message: string
  model_info?: {
    reasoning_model?: string
    creative_model?: string
    reasoning_provider?: string
    creative_provider?: string
    reasoning_success?: boolean
    creative_success?: boolean
  }
  reasoning_supported?: boolean
  response_time_ms?: number
} | null>(null)

async function runTest() {
  testing.value = true
  testResult.value = null

  try {
    const result = await systemApi.testModel()
    testResult.value = result

    if (result.success) {
      showToast('模型连接测试成功', 'success')
    } else {
      showToast('模型连接测试失败', 'error')
    }
  } catch (error: any) {
    showToast('测试请求异常: ' + (error.message || '未知错误'), 'error')
    testResult.value = {
      success: false,
      message: error.message || '请求异常'
    }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="api-test-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        <Icon name="zap" :size="16" />
        API 测试
      </h3>
    </div>

    <div class="panel-body">
      <button
        class="test-btn"
        :disabled="testing"
        @click="runTest"
      >
        <Icon v-if="testing" name="loader" :size="16" class="spin" />
        <Icon v-else name="play" :size="16" />
        {{ testing ? '测试中...' : '运行测试' }}
      </button>

      <div v-if="testResult" class="result-card" :class="{ success: testResult.success, error: !testResult.success }">
        <div class="result-status">
          <Icon v-if="testResult.success" name="check-circle" :size="16" class="status-icon" />
          <Icon v-else name="x-circle" :size="16" class="status-icon" />
          <span>{{ testResult.success ? '成功' : '失败' }}</span>
          <span v-if="testResult.response_time_ms" class="response-time">
            {{ testResult.response_time_ms }}ms
          </span>
        </div>

        <div class="result-message">{{ testResult.message }}</div>

        <div v-if="testResult.model_info" class="model-info">
          <div class="model-section">
            <div class="section-title">推理模型</div>
            <div class="info-row">
              <span class="label">模型:</span>
              <span class="value">{{ testResult.model_info.reasoning_model }}</span>
            </div>
            <div class="info-row">
              <span class="label">提供商:</span>
              <span class="value">{{ testResult.model_info.reasoning_provider }}</span>
            </div>
            <div class="info-row">
              <span class="label">状态:</span>
              <span class="value" :class="{ supported: testResult.model_info.reasoning_success }">
                {{ testResult.model_info.reasoning_success ? '✓ 连接成功' : '✗ 连接失败' }}
              </span>
            </div>
          </div>

          <div class="model-section">
            <div class="section-title">创意模型</div>
            <div class="info-row">
              <span class="label">模型:</span>
              <span class="value">{{ testResult.model_info.creative_model }}</span>
            </div>
            <div class="info-row">
              <span class="label">提供商:</span>
              <span class="value">{{ testResult.model_info.creative_provider }}</span>
            </div>
            <div class="info-row">
              <span class="label">状态:</span>
              <span class="value" :class="{ supported: testResult.model_info.creative_success }">
                {{ testResult.model_info.creative_success ? '✓ 连接成功' : '✗ 连接失败' }}
              </span>
            </div>
          </div>

          <div class="info-row">
            <span class="label">推理支持:</span>
            <span class="value" :class="{ supported: testResult.reasoning_supported }">
              {{ testResult.reasoning_supported ? '✓ 支持' : '✗ 不支持' }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.api-test-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-panel);
}

.panel-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.test-btn {
  width: 100%;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.test-btn:hover:not(:disabled) {
  background: var(--accent-600);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
}

.test-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.result-card {
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.result-card.success {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.05);
}

.result-card.error {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.result-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.status-icon {
  color: var(--accent-500);
}

.success .status-icon {
  color: #10b981;
}

.error .status-icon {
  color: #ef4444;
}

.response-time {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}

.result-message {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 12px;
  word-break: break-word;
}

.model-info {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.model-section {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--bg-panel);
  border-radius: 6px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
}

.label {
  color: var(--text-muted);
  min-width: 80px;
}

.value {
  color: var(--text-primary);
  font-weight: 500;
}

.value.supported {
  color: #10b981;
}

.value.error {
  color: #ef4444;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
