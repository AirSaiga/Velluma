<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { systemApi } from '../services/api'
import type { ModelConfig, ModelConfigUpdatePayload } from '../services/api'
import { useToast } from '../composables/useToast'
import Icon from './Icon.vue'

const { showToast } = useToast()

// ============================================================
// 表单状态
// ============================================================

type ProfileRole = 'reasoning' | 'creative'

interface ProfileForm {
  provider: string
  model: string
  api_key: string // 留空表示保持不变（服务端仅返回掩码）
  base_url: string
  enabled: boolean
  effort: string
}

const profileRoles: ProfileRole[] = ['reasoning', 'creative']

const profileForms = reactive<Record<ProfileRole, ProfileForm>>({
  reasoning: { provider: 'openrouter', model: '', api_key: '', base_url: '', enabled: false, effort: 'medium' },
  creative: { provider: 'openrouter', model: '', api_key: '', base_url: '', enabled: false, effort: 'medium' },
})

/** 服务端返回的 Key 掩码信息（用于 placeholder 提示） */
const profileMeta = reactive<Record<ProfileRole, { has_api_key: boolean; api_key_masked: string }>>({
  reasoning: { has_api_key: false, api_key_masked: '' },
  creative: { has_api_key: false, api_key_masked: '' },
})

const embeddingForm = reactive({ model: '', api_key: '', dimensions: 1536 })
const embeddingMeta = reactive({ has_api_key: false, api_key_masked: '' })

const proxyForm = reactive({ enabled: true, url: '' })

/** 提供商默认 Base URL（placeholder 提示用，与后端 DEFAULT_PROVIDER_URLS 对应） */
const PROVIDER_DEFAULT_URLS: Record<string, string> = {
  openrouter: 'https://openrouter.ai/api/v1',
  volcengine: 'https://ark.cn-beijing.volces.com/api/v3',
  deepseek: 'https://api.deepseek.com/v1',
}

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: 'OpenRouter',
  volcengine: '火山引擎 (Volcengine)',
  deepseek: 'DeepSeek',
}

const loading = ref(false)
const loadError = ref<string | null>(null)
const saving = ref(false)

function applyConfig(config: ModelConfig) {
  for (const role of profileRoles) {
    const p = config.llm[role]
    profileForms[role].provider = p.provider
    profileForms[role].model = p.model
    profileForms[role].base_url = p.base_url
    profileForms[role].enabled = p.enabled
    profileForms[role].effort = p.effort
    profileForms[role].api_key = '' // 不回填明文，留空即保持
    profileMeta[role].has_api_key = p.has_api_key
    profileMeta[role].api_key_masked = p.api_key_masked
  }
  embeddingForm.model = config.embedding.model
  embeddingForm.dimensions = config.embedding.dimensions
  embeddingForm.api_key = ''
  embeddingMeta.has_api_key = config.embedding.has_api_key
  embeddingMeta.api_key_masked = config.embedding.api_key_masked
  proxyForm.enabled = config.proxy.enabled
  proxyForm.url = config.proxy.url
}

async function loadConfig() {
  loading.value = true
  loadError.value = null
  try {
    const config = await systemApi.getModelConfig()
    applyConfig(config)
  } catch (error: any) {
    loadError.value = '加载配置失败: ' + (error.message || '未知错误')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload: ModelConfigUpdatePayload = {
      reasoning: { ...profileForms.reasoning, api_key: profileForms.reasoning.api_key || undefined },
      creative: { ...profileForms.creative, api_key: profileForms.creative.api_key || undefined },
      embedding: {
        model: embeddingForm.model,
        dimensions: embeddingForm.dimensions,
        api_key: embeddingForm.api_key || undefined,
      },
      proxy: { enabled: proxyForm.enabled, url: proxyForm.url },
    }
    const config = await systemApi.updateModelConfig(payload)
    applyConfig(config)
    showToast('设置已保存', 'success')
  } catch (error: any) {
    showToast('保存失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    saving.value = false
  }
}

// ============================================================
// 连接测试
// ============================================================

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

onMounted(loadConfig)
</script>

<template>
  <div class="settings-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        <Icon name="settings" :size="16" />
        模型设置
      </h3>
    </div>

    <div class="panel-body">
      <div v-if="loadError" class="error-banner">{{ loadError }}</div>
      <div v-else-if="loading" class="loading-hint">
        <Icon name="loader" :size="14" class="spin" />
        加载配置中...
      </div>

      <template v-else>
        <!-- LLM 配置 -->
        <section v-for="role in profileRoles" :key="role" class="config-section">
          <div class="section-header">{{ role === 'reasoning' ? '推理模型' : '创意模型' }}</div>

          <label class="field">
            <span class="field-label">提供商</span>
            <select v-model="profileForms[role].provider" class="field-input">
              <option v-for="(label, value) in PROVIDER_LABELS" :key="value" :value="value">{{ label }}</option>
            </select>
          </label>

          <label class="field">
            <span class="field-label">模型</span>
            <input
              v-model="profileForms[role].model"
              class="field-input"
              :placeholder="role === 'reasoning' ? '如 deepseek-reasoner' : '如 deepseek-chat'"
            />
          </label>

          <label class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="profileForms[role].api_key"
              type="password"
              class="field-input"
              :placeholder="profileMeta[role].has_api_key
                ? `已保存 (${profileMeta[role].api_key_masked})，留空保持不变`
                : '输入 API Key'"
              autocomplete="new-password"
            />
          </label>

          <label class="field">
            <span class="field-label">Base URL</span>
            <input
              v-model="profileForms[role].base_url"
              class="field-input"
              :placeholder="PROVIDER_DEFAULT_URLS[profileForms[role].provider] || 'API 地址'"
            />
          </label>

          <label class="field-inline">
            <input v-model="profileForms[role].enabled" type="checkbox" />
            <span>启用深度思考（Reasoning）</span>
          </label>

          <label v-if="profileForms[role].enabled" class="field">
            <span class="field-label">推理强度</span>
            <select v-model="profileForms[role].effort" class="field-input">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </label>
        </section>

        <!-- Embedding 配置 -->
        <section class="config-section">
          <div class="section-header">Embedding（向量记忆）</div>

          <label class="field">
            <span class="field-label">模型</span>
            <input v-model="embeddingForm.model" class="field-input" placeholder="text-embedding-v2" />
          </label>

          <label class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="embeddingForm.api_key"
              type="password"
              class="field-input"
              :placeholder="embeddingMeta.has_api_key
                ? `已保存 (${embeddingMeta.api_key_masked})，留空保持不变`
                : '输入 DashScope API Key'"
              autocomplete="new-password"
            />
          </label>

          <label class="field">
            <span class="field-label">向量维度</span>
            <input v-model.number="embeddingForm.dimensions" type="number" min="1" class="field-input" />
          </label>
          <div class="field-warning">
            修改维度需重启后端；重启迁移会删列重建，清空全部向量记忆数据。
          </div>
        </section>

        <!-- 代理配置 -->
        <section class="config-section">
          <div class="section-header">网络代理</div>

          <label class="field-inline">
            <input v-model="proxyForm.enabled" type="checkbox" />
            <span>启用代理</span>
          </label>

          <label v-if="proxyForm.enabled" class="field">
            <span class="field-label">代理地址</span>
            <input v-model="proxyForm.url" class="field-input" placeholder="http://127.0.0.1:4780" />
          </label>
        </section>

        <button class="save-btn" :disabled="saving" @click="save">
          <Icon v-if="saving" name="loader" :size="16" class="spin" />
          <Icon v-else name="check" :size="16" />
          {{ saving ? '保存中...' : '保存设置' }}
        </button>
        <div class="save-hint">保存后 LLM 与代理配置立即生效，无需重启。</div>

        <!-- 连接测试 -->
        <section class="config-section test-section">
          <div class="section-header">连接测试</div>

          <button class="test-btn" :disabled="testing" @click="runTest">
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
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.settings-panel {
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

.loading-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
  padding: 12px 0;
}

.error-banner {
  padding: 12px;
  font-size: 13px;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid #ef4444;
  border-radius: 8px;
}

/* ---------- 配置区块 ---------- */

.config-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.section-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.field {
  display: block;
  margin-bottom: 10px;
}

.field-label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.field-input {
  width: 100%;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  outline: none;
  transition: border-color 0.2s ease;
}

.field-input:focus {
  border-color: var(--accent-500);
}

.field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}

.field-warning {
  font-size: 12px;
  line-height: 1.5;
  color: #f59e0b;
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.08);
  border-radius: 6px;
}

/* ---------- 保存 ---------- */

.save-btn {
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

.save-btn:hover:not(:disabled) {
  background: var(--accent-600);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.save-hint {
  margin: 8px 0 20px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

/* ---------- 连接测试 ---------- */

.test-section {
  border-bottom: none;
  margin-bottom: 0;
}

.test-btn {
  width: 100%;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.test-btn:hover:not(:disabled) {
  background: var(--accent-500);
  color: white;
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
