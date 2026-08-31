<script setup lang="ts">
/**
 * 全局设置弹窗（取代旧 bible 页「设置」分区的整页 SettingsPanel）。
 *
 * 应用级配置（模型 / 向量记忆 / 代理 / 通知偏好），全局生效、与书籍无关。
 * 每次打开时重新拉取配置；保存后 LLM 与代理立即生效（embedding 维度变更需重启）。
 */
import { reactive, ref, watch } from 'vue'
import ModalShell from '../features/world/presentation/ModalShell.vue'
import { systemApi } from '../services/api'
import type { ModelConfig, ModelConfigUpdatePayload, VendorCatalogEntry } from '../services/api'
import { useAppSettings } from '../composables/useAppSettings'
import { useToast } from '../composables/useToast'
import { useNotifyPrefs } from '../composables/useNotifyPrefs'
import Icon from './Icon.vue'

const { visible, close } = useAppSettings()
const { showToast } = useToast()
const { prefs: notifyPrefs, setInApp, setSystem } = useNotifyPrefs()

// ============================================================
// 表单状态
// ============================================================

type ProfileRole = 'reasoning' | 'creative'

interface ProfileForm {
  model: string
  api_key: string // 留空表示保持不变（服务端仅返回掩码）
  base_url: string
  enabled: boolean
  effort: string
}

const profileRoles: ProfileRole[] = ['reasoning', 'creative']

const profileForms = reactive<Record<ProfileRole, ProfileForm>>({
  reasoning: { model: '', api_key: '', base_url: '', enabled: false, effort: 'medium' },
  creative: { model: '', api_key: '', base_url: '', enabled: false, effort: 'medium' },
})

/** 服务端返回的 Key 掩码信息（用于 placeholder 提示） */
const profileMeta = reactive<Record<ProfileRole, { has_api_key: boolean; api_key_masked: string; configured?: boolean }>>({
  reasoning: { has_api_key: false, api_key_masked: '' },
  creative: { has_api_key: false, api_key_masked: '' },
})

const ROLE_LABELS: Record<ProfileRole, string> = {
  reasoning: '分析模型（审阅·诊断）',
  creative: '写作模型（正文生成）',
}

/** 每个槽位的职责说明（帮助用户理解该配什么模型） */
const ROLE_HINTS: Record<ProfileRole, string> = {
  reasoning: '审阅章节、推断写作意图、检查一致性等「判断」任务',
  creative: '续写正文、生成挂件、缝合碎片等所有「写作」任务',
}

const MODEL_PLACEHOLDERS: Record<ProfileRole, string> = {
  reasoning: '如 deepseek-v4-flash',
  creative: '如 kimi-k2.6',
}

// ============================================================
// 厂商能力目录（2026-08-28 五厂商调研）：选厂商自动填 base_url + 模型候选 + 提示
// ============================================================

const vendorCatalog = ref<VendorCatalogEntry[]>([])
/** 每槽位的厂商选择（'custom' = 自定义/其他，自由输入 base_url） */
const vendorSelection = reactive<Record<ProfileRole, string>>({
  reasoning: 'custom',
  creative: 'custom',
})

/** base_url 域名 → 厂商 id（与后端 vendor_profiles.detect_provider 同判据） */
const DOMAIN_FRAGMENTS: [string, string][] = [
  ['api.deepseek.com', 'deepseek'],
  ['bigmodel.cn', 'glm'],
  ['moonshot.cn', 'kimi'],
  ['moonshot.ai', 'kimi'],
  ['xiaomimimo.com', 'mimo'],
  ['dashscope.aliyuncs.com', 'qwen'],
  ['maas.aliyuncs.com', 'qwen'],
  ['api.openai.com', 'openai'],
  ['openrouter.ai', 'openrouter'],
  ['localhost', 'local'],
  ['127.0.0.1', 'local'],
]

function matchVendorByBaseUrl(url: string): string {
  if (!url) return 'custom'
  const lowered = url.toLowerCase()
  for (const [fragment, id] of DOMAIN_FRAGMENTS) {
    if (lowered.includes(fragment)) return id
  }
  return 'custom'
}

function currentVendor(role: ProfileRole): VendorCatalogEntry | null {
  return vendorCatalog.value.find((v) => v.id === vendorSelection[role]) || null
}

function vendorModels(role: ProfileRole): { id: string; label: string; note: string }[] {
  return currentVendor(role)?.models || []
}

/** 厂商能力提示 + 模型级动态警示（弃用/下线/强制思考） */
function vendorNotes(role: ProfileRole): string[] {
  return currentVendor(role)?.notes || []
}

function modelWarning(role: ProfileRole): string {
  const m = profileForms[role].model.trim().toLowerCase()
  const b = profileForms[role].base_url.toLowerCase()
  if (!m) return ''
  if (b.includes('deepseek') && (m === 'deepseek-chat' || m === 'deepseek-reasoner')) {
    return '⚠ 该模型名已于 2026-07-24 弃用，请换 deepseek-v4-flash / deepseek-v4-pro'
  }
  if (b.includes('moonshot') && (m.startsWith('moonshot-v1') || m === 'kimi-k2.5')) {
    return '⚠ 该模型 2026-08-31 全平台下线，请换 kimi-k2.6'
  }
  if (b.includes('bigmodel') && m.startsWith('glm-5.3') && !profileForms[role].enabled) {
    return '⚠ glm-5.3 强制思考无法关闭；此槽若要关思考请换 glm-5.2 或免费的 glm-4.7-flash'
  }
  return ''
}

/** 手选厂商：自动填推荐 base_url（模型名保留，可从候选里选或继续手输） */
function onVendorChange(role: ProfileRole) {
  if (vendorSelection[role] === 'custom') return
  const entry = currentVendor(role)
  if (entry?.base_url) profileForms[role].base_url = entry.base_url
}

async function loadCatalog() {
  if (vendorCatalog.value.length) return
  try {
    vendorCatalog.value = (await systemApi.getModelCatalog()).vendors
  } catch {
    /* 静默回退：目录拿不到时厂商下拉只剩「自定义」，行为同旧版 */
  }
}

const embeddingForm = reactive({ model: '', api_key: '', base_url: '', dimensions: 1536, follow_llm: false })
const embeddingMeta = reactive({ has_api_key: false, api_key_masked: '' })
/** 跟随模式下实际生效的文本模型连接预览（GET 返回） */
const embeddingInherited = reactive<{ source: 'creative' | 'reasoning' | null; base_url: string; has_api_key: boolean }>({
  source: null,
  base_url: '',
  has_api_key: false,
})
/** 专业级折叠：向量记忆（默认收起——未配置时走结构化+词法默认记忆流） */
const showAdvanced = ref(false)

// ============================================================
// 去 AI 味小模型（deai/ 子项目，实验）：卡片舱续写短稿上屏前的抛光
// ============================================================

const showDeai = ref(false)
const deaiForm = reactive({ enabled: false, model: '', api_key: '', base_url: '' })
const deaiMeta = reactive({ has_api_key: false, api_key_masked: '', effective_model: '', effective_base_url: '' })
const deaiTesting = ref(false)
const deaiTestResult = ref<{
  success: boolean
  message: string
  input_text: string
  output_text: string
  applied: boolean
  elapsed_ms: number
} | null>(null)

const proxyForm = reactive({ enabled: true, url: '' })

const loading = ref(false)
const loadError = ref<string | null>(null)
const saving = ref(false)

function applyConfig(config: ModelConfig) {
  for (const role of profileRoles) {
    const p = config.llm[role]
    profileForms[role].model = p.model
    profileForms[role].base_url = p.base_url
    profileForms[role].enabled = p.enabled
    profileForms[role].effort = p.effort
    profileForms[role].api_key = '' // 不回填明文，留空即保持
    profileMeta[role].has_api_key = p.has_api_key
    profileMeta[role].api_key_masked = p.api_key_masked
    profileMeta[role].configured = p.configured
    vendorSelection[role] = matchVendorByBaseUrl(p.base_url)
  }
  embeddingForm.model = config.embedding.model
  embeddingForm.dimensions = config.embedding.dimensions
  embeddingForm.base_url = config.embedding.base_url
  embeddingForm.follow_llm = config.embedding.follow_llm
  embeddingForm.api_key = ''
  embeddingMeta.has_api_key = config.embedding.has_api_key
  embeddingMeta.api_key_masked = config.embedding.api_key_masked
  embeddingInherited.source = config.embedding.inherited?.source ?? null
  embeddingInherited.base_url = config.embedding.inherited?.base_url ?? ''
  embeddingInherited.has_api_key = config.embedding.inherited?.has_api_key ?? false
  const deai = config.deai
  deaiForm.enabled = deai?.enabled ?? false
  deaiForm.model = deai?.model ?? ''
  deaiForm.base_url = deai?.base_url ?? ''
  deaiForm.api_key = '' // 不回填明文，留空即保持
  deaiMeta.has_api_key = deai?.has_api_key ?? false
  deaiMeta.api_key_masked = deai?.api_key_masked ?? ''
  deaiMeta.effective_model = deai?.effective_model ?? ''
  deaiMeta.effective_base_url = deai?.effective_base_url ?? ''
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
        follow_llm: embeddingForm.follow_llm,
        base_url: embeddingForm.base_url,
        api_key: embeddingForm.api_key || undefined,
      },
      deai: {
        enabled: deaiForm.enabled,
        model: deaiForm.model,
        base_url: deaiForm.base_url,
        api_key: deaiForm.api_key || undefined,
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
    reasoning_success?: boolean
    creative_success?: boolean
    embedding_configured?: boolean
    embedding_model?: string
    embedding_success?: boolean
    embedding_dimensions_returned?: number | null
    embedding_dimensions_expected?: number | null
  }
  reasoning_supported?: boolean
  response_time_ms?: number
} | null>(null)

async function runTest() {
  testing.value = true
  testResult.value = null

  try {
    // 向量模型用表单实时值探测（未保存也能测）；api_key 留空由后端沿用已保存 Key
    const result = await systemApi.testModel({
      model: embeddingForm.model,
      base_url: embeddingForm.base_url,
      dimensions: embeddingForm.dimensions,
      follow_llm: embeddingForm.follow_llm,
      api_key: embeddingForm.api_key || undefined,
    })
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

// ============================================================
// 去 AI 味小模型：试一试（表单实时值，未保存也能测）
// ============================================================

async function runDeaiTest() {
  deaiTesting.value = true
  deaiTestResult.value = null
  try {
    const result = await systemApi.testDeai({
      model: deaiForm.model || undefined,
      base_url: deaiForm.base_url || undefined,
      api_key: deaiForm.api_key || undefined,
    })
    deaiTestResult.value = result
    // 契约§6 保底回退（事实被改→回退原文）不算失败——闸门在工作
    if (result.success) {
      showToast('小模型调用走通', 'success')
    } else if (result.skipped) {
      showToast('未发起调用：' + result.message, 'error')
    } else {
      showToast('小模型调用失败', 'error')
    }
  } catch (error: any) {
    showToast('试一试请求异常: ' + (error.message || '未知错误'), 'error')
  } finally {
    deaiTesting.value = false
  }
}

// 每次打开弹窗重新拉取配置（本地后端，开销可忽略），并清掉上次测试结果
watch(visible, (v) => {
  if (v) {
    loadConfig()
    loadCatalog()
    testResult.value = null
    deaiTestResult.value = null
  }
})
</script>

<template>
  <ModalShell
    v-if="visible"
    title="设置"
    subtitle="模型与偏好，全局生效，与具体书籍无关"
    width="720px"
    @close="close"
  >
    <div v-if="loadError" class="error-banner">{{ loadError }}</div>
    <div v-else-if="loading" class="loading-hint">
      <Icon name="loader" :size="14" class="spin" />
      加载配置中...
    </div>

    <template v-else>
      <!-- LLM 双模型并排（字段集相同，天然对称） -->
      <div class="profiles-grid">
        <section v-for="role in profileRoles" :key="role" class="profile-card">
          <div class="profile-title">{{ ROLE_LABELS[role] }}</div>
          <div class="profile-hint">{{ ROLE_HINTS[role] }}</div>
          <div v-if="role === 'reasoning'" class="profile-hint profile-hint-sub">
            留空（模型名与 Key 均不填）则自动跟随写作模型。
          </div>

          <label class="field">
            <span class="field-label">厂商</span>
            <select
              v-model="vendorSelection[role]"
              class="field-input"
              @change="onVendorChange(role)"
            >
              <option value="custom">自定义 / 其他</option>
              <option v-for="v in vendorCatalog" :key="v.id" :value="v.id">{{ v.label }}</option>
            </select>
          </label>

          <label class="field">
            <span class="field-label">模型</span>
            <input
              v-model="profileForms[role].model"
              class="field-input"
              :list="`model-options-${role}`"
              :placeholder="MODEL_PLACEHOLDERS[role]"
            />
            <datalist :id="`model-options-${role}`">
              <option v-for="m in vendorModels(role)" :key="m.id" :value="m.id">{{ m.label }}——{{ m.note }}</option>
            </datalist>
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
              placeholder="https://api.deepseek.com/v1"
            />
          </label>

          <div class="flags-row">
            <label class="field-inline">
              <input v-model="profileForms[role].enabled" type="checkbox" />
              <span>深度思考（Reasoning）</span>
            </label>
            <select v-if="profileForms[role].enabled" v-model="profileForms[role].effort" class="effort-select">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </div>

          <!-- 厂商能力提示（目录静态）+ 模型级动态警示（弃用/下线/强制思考） -->
          <div v-for="n in vendorNotes(role)" :key="n" class="field-sub-hint">{{ n }}</div>
          <div v-if="modelWarning(role)" class="field-sub-hint profile-warn">{{ modelWarning(role) }}</div>
        </section>
      </div>

      <!-- Embedding 配置（专业级：默认折叠——未配置时走结构化+词法记忆流） -->
      <button type="button" class="advanced-toggle" @click="showAdvanced = !showAdvanced">
        <span>专业级：向量记忆（Embedding）</span>
        <span class="advanced-caret">{{ showAdvanced ? '▾' : '▸' }}</span>
      </button>

      <template v-if="showAdvanced">
        <div class="field-hint">
          未配置时使用结构化 + 词法记忆（默认，无需额外服务）；配置后启用向量召回增强（任意 OpenAI 兼容 Embedding 服务 + pgvector）。
        </div>

        <label class="field-inline follow-toggle">
          <input v-model="embeddingForm.follow_llm" type="checkbox" />
          <span>连接跟随文本模型（与写作模型共用 Key 与 Base URL，换文本模型即同步）</span>
        </label>

        <div class="embedding-grid" :class="{ follow: embeddingForm.follow_llm }">
          <label class="field">
            <span class="field-label">模型</span>
            <input v-model="embeddingForm.model" class="field-input" placeholder="text-embedding-v2" />
          </label>

          <label v-if="!embeddingForm.follow_llm" class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="embeddingForm.api_key"
              type="password"
              class="field-input"
              :placeholder="embeddingMeta.has_api_key
                ? `已保存 (${embeddingMeta.api_key_masked})，留空保持不变`
                : '输入 API Key'"
              autocomplete="new-password"
            />
          </label>

          <label class="field">
            <span class="field-label">向量维度</span>
            <input v-model.number="embeddingForm.dimensions" type="number" min="1" class="field-input" />
          </label>
        </div>

        <label v-if="!embeddingForm.follow_llm" class="field">
          <span class="field-label">Base URL</span>
          <input
            v-model="embeddingForm.base_url"
            class="field-input"
            placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
          />
          <span class="field-sub-hint">任意 OpenAI 兼容端点；留空默认阿里云 DashScope 兼容模式。</span>
        </label>

        <div v-else class="field-hint" :class="{ 'follow-missing': !embeddingInherited.has_api_key }">
          <template v-if="embeddingInherited.has_api_key">
            将使用{{ embeddingInherited.source === 'reasoning' ? '分析' : '写作' }}模型的连接：{{ embeddingInherited.base_url || '（默认端点）' }}，向量模型名填该服务商提供的 Embedding 模型。
          </template>
          <template v-else>
            写作/分析模型均未配置 API Key——跟随模式下向量记忆不可用，请先在上面配置文本模型。
          </template>
        </div>

        <div class="field-warning">
          修改维度需重启后端；重启迁移会删列重建，清空全部向量记忆数据。
        </div>
      </template>

      <!-- 去 AI 味小模型（deai/ 子项目，实验）：卡片舱续写短稿上屏前的抛光 -->
      <button type="button" class="advanced-toggle deai-toggle" @click="showDeai = !showDeai">
        <span>实验：去 AI 味小模型（续写短稿抛光）</span>
        <span class="advanced-caret">{{ showDeai ? '▾' : '▸' }}</span>
      </button>

      <template v-if="showDeai">
        <div class="field-hint">
          续写草稿上屏前，用部署在阿里云百炼的自训小模型再做一轮「像人改写」——只改语言质感，
          不动事实、数字、专名；模型改坏事实会自动回退原文。只处理 100 字以内的短稿，长稿自动跳过。
        </div>

        <label class="field-inline follow-toggle">
          <input v-model="deaiForm.enabled" type="checkbox" />
          <span>启用（未启用或未填 Key 时，写作流程零变化）</span>
        </label>

        <div class="deai-grid">
          <label class="field">
            <span class="field-label">模型（部署名）</span>
            <input
              v-model="deaiForm.model"
              class="field-input"
              :placeholder="deaiMeta.effective_model || 'qwen3-4b-instruct-2507-…'"
            />
            <span class="field-sub-hint">百炼「部署管理」里的部署名；重新部署后会变，需回来更新。</span>
          </label>

          <label class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="deaiForm.api_key"
              type="password"
              class="field-input"
              :placeholder="deaiMeta.has_api_key
                ? `已保存 (${deaiMeta.api_key_masked})，留空保持不变`
                : '阿里云百炼 DashScope API Key'"
              autocomplete="new-password"
            />
          </label>
        </div>

        <div class="deai-actions">
          <button type="button" class="btn-secondary" :disabled="deaiTesting" @click="runDeaiTest">
            <Icon v-if="deaiTesting" name="loader" :size="14" class="spin" />
            <Icon v-else name="play" :size="14" />
            {{ deaiTesting ? '试一试中...' : '试一试' }}
          </button>
          <span v-if="deaiMeta.effective_base_url" class="field-sub-hint">{{ deaiMeta.effective_base_url }}</span>
        </div>

        <div v-if="deaiTestResult" class="deai-result" :class="{ success: deaiTestResult.success, error: !deaiTestResult.success }">
          <div class="test-status">
            <span class="status-text">{{ deaiTestResult.message }}</span>
            <span v-if="deaiTestResult.elapsed_ms" class="response-time">{{ deaiTestResult.elapsed_ms }}ms</span>
          </div>
          <div v-if="deaiTestResult.input_text" class="deai-diff">
            <div>原文：{{ deaiTestResult.input_text }}</div>
            <div>结果：{{ deaiTestResult.output_text }}<span v-if="!deaiTestResult.applied" class="deai-notapplied">（未采纳，见上方说明）</span></div>
          </div>
        </div>
      </template>

      <!-- 代理 + 通知偏好：各占一列的窄行 -->
      <div class="misc-grid">
        <section>
          <div class="misc-title">网络代理</div>
          <label class="field-inline">
            <input v-model="proxyForm.enabled" type="checkbox" />
            <span>启用代理</span>
          </label>
          <input
            v-if="proxyForm.enabled"
            v-model="proxyForm.url"
            class="field-input"
            placeholder="http://127.0.0.1:4780"
          />
        </section>

        <section>
          <div class="misc-title">通知偏好</div>
          <label class="field-inline">
            <input
              type="checkbox"
              :checked="notifyPrefs.inApp"
              @change="setInApp(($event.target as HTMLInputElement).checked)"
            />
            <span>生成完成时弹出提示框</span>
          </label>
          <label class="field-inline">
            <input
              type="checkbox"
              :checked="notifyPrefs.system"
              @change="setSystem(($event.target as HTMLInputElement).checked)"
            />
            <span>切走时使用 Windows 系统通知</span>
          </label>
        </section>
      </div>

      <!-- 连接测试结果（紧凑条） -->
      <div v-if="testResult" class="test-result" :class="{ success: testResult.success, error: !testResult.success }">
        <div class="test-status">
          <Icon v-if="testResult.success" name="check-circle" :size="14" class="status-icon" />
          <Icon v-else name="x-circle" :size="14" class="status-icon" />
          <span class="status-text">{{ testResult.success ? '连接成功' : '连接失败' }}</span>
          <span v-if="testResult.response_time_ms" class="response-time">{{ testResult.response_time_ms }}ms</span>
        </div>
        <div class="test-message">{{ testResult.message }}</div>
        <div v-if="testResult.model_info" class="test-detail">
          推理 {{ testResult.model_info.reasoning_model }} {{ testResult.model_info.reasoning_success ? '✓' : '✗' }}
          · 写作 {{ testResult.model_info.creative_model }} {{ testResult.model_info.creative_success ? '✓' : '✗' }}
          · 深度思考{{ testResult.reasoning_supported ? '支持' : '不支持' }}
          <template v-if="testResult.model_info.embedding_configured === false">
            · 向量 未配置（跳过）
          </template>
          <template v-else-if="testResult.model_info.embedding_model">
            · 向量 {{ testResult.model_info.embedding_model }} {{ testResult.model_info.embedding_success ? '✓' : '✗' }}<template v-if="testResult.model_info.embedding_dimensions_returned">（{{ testResult.model_info.embedding_dimensions_returned }} 维）</template>
          </template>
        </div>
      </div>
    </template>

    <template #footer>
      <button class="btn-secondary footer-test" :disabled="testing || loading" @click="runTest">
        <Icon v-if="testing" name="loader" :size="14" class="spin" />
        <Icon v-else name="play" :size="14" />
        {{ testing ? '测试中...' : '连接测试' }}
      </button>
      <span class="footer-hint">保存后 LLM 与代理立即生效，无需重启</span>
      <button class="btn-primary" :disabled="saving || loading" @click="save">
        <Icon v-if="saving" name="loader" :size="14" class="spin" />
        <Icon v-else name="check" :size="14" />
        {{ saving ? '保存中...' : '保存设置' }}
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
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

/* ---------- 双模型并排 ---------- */

.profiles-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.profile-card {
  padding: 12px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.profile-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 4px;
}

.profile-hint {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.profile-hint-sub {
  margin-top: -6px;
  color: #f59e0b;
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
  padding: 7px 10px;
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

.flags-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}

.flags-row .field-inline {
  margin-bottom: 0;
}

.effort-select {
  padding: 4px 6px;
  font-size: 12px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  outline: none;
}

/* ---------- 专业级折叠（向量记忆） ---------- */

.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 6px 8px;
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.advanced-toggle:hover {
  color: var(--text-secondary);
  border-color: var(--text-muted);
}

.advanced-caret {
  font-size: 11px;
}

.field-hint {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  padding: 8px 2px 4px;
}

.embedding-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 110px;
  gap: 10px;
}

.embedding-grid.follow {
  grid-template-columns: 1fr 110px;
}

.follow-toggle {
  margin: 4px 0 10px;
  font-size: 12px;
  color: var(--text-secondary);
}

.field-sub-hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-muted);
}

.follow-missing {
  color: #f59e0b;
}

/* 模型级动态警示（弃用/下线/强制思考）——比普通提示醒目但不打断 */
.profile-warn {
  color: #d97706;
}

.field-warning {
  font-size: 12px;
  line-height: 1.5;
  color: #f59e0b;
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.08);
  border-radius: 6px;
  margin-bottom: 10px;
}

/* ---------- 去 AI 味小模型（deai） ---------- */

.deai-toggle {
  margin-top: 12px;
}

.deai-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.deai-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0 10px;
}

.deai-result {
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 12px;
}

.deai-result.success {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.05);
}

.deai-result.error {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.deai-result .status-text {
  font-weight: 600;
  color: var(--text-primary);
}

.deai-diff {
  margin-top: 6px;
  display: grid;
  gap: 4px;
  line-height: 1.6;
  color: var(--text-secondary);
  word-break: break-word;
}

.deai-notapplied {
  margin-left: 6px;
  color: var(--text-muted);
}

/* ---------- 代理 + 通知偏好 ---------- */

.misc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.misc-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

/* ---------- 连接测试结果（紧凑条） ---------- */

.test-result {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 12px;
}

.test-result.success {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.05);
}

.test-result.error {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.test-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.test-result .status-icon {
  color: var(--accent-500);
}

.test-result.success .status-icon {
  color: #10b981;
}

.test-result.error .status-icon {
  color: #ef4444;
}

.response-time {
  margin-left: auto;
  font-weight: 400;
  color: var(--text-muted);
}

.test-message {
  margin-top: 4px;
  line-height: 1.5;
  color: var(--text-secondary);
  word-break: break-word;
}

.test-detail {
  margin-top: 4px;
  color: var(--text-muted);
}

/* ---------- 底部按钮 ---------- */

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-primary {
  color: white;
  background: var(--accent-500);
  border: none;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}

.btn-secondary {
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--accent-500);
  color: white;
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.footer-test {
  margin-right: auto;
}

.footer-hint {
  align-self: center;
  font-size: 12px;
  color: var(--text-muted);
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

/* 窄屏（小窗口）时双列回落单列 */
@media (max-width: 640px) {
  .profiles-grid,
  .misc-grid,
  .embedding-grid,
  .deai-grid {
    grid-template-columns: 1fr;
  }
}
</style>
