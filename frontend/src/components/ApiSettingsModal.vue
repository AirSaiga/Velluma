<script setup lang="ts">
/**
 * 模型与 API 弹窗（2026-09-15 设置拆分：从旧「设置」大弹窗独立）。
 *
 * 只管「AI 用什么模型、连什么服务」：LLM 双槽（分析/写作）+ 配置预设 +
 * 厂商目录 + 向量记忆 + 去 AI 味小模型 + 网络代理 + 连接测试。全局生效、
 * 与书籍无关；每次打开重拉配置，保存后 LLM 与代理立即生效（向量维度变更
 * 需重启）。外观/通知已分设独立入口，不再混装于此。
 */
import { reactive, ref, watch } from 'vue'
import ModalShell from './ModalShell.vue'
import { systemApi } from '../services/api'
import type { ModelConfig, ModelConfigUpdatePayload, VendorCatalogEntry, ModelPresetItem } from '../services/api'
import { useAppSettings } from '../composables/useAppSettings'
import { useToast } from '../composables/useToast'
import Icon from './Icon.vue'

const { apiVisible: visible, closeApi: close } = useAppSettings()
const { showToast } = useToast()

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
  reasoning: '如 deepseek-flash',
  creative: '如 kimi-k2.6',
}

const ROLE_SHORT_LABELS: Record<ProfileRole, string> = {
  reasoning: '分析模型',
  creative: '写作模型',
}

// ============================================================
// 模型配置预设（快速切换，2026-09-11）：切走前整套存档（含 Key），下拉一点切回；
// 服务端另有自动存档安全网——覆盖槽位连接时旧值不完整或已存档才会丢，正常切换永不丢
// ============================================================

const presets = ref<ModelPresetItem[]>([])
const presetSelection = reactive<Record<ProfileRole, string>>({ reasoning: '', creative: '' })
const presetNameDraft = reactive<Record<ProfileRole, string>>({ reasoning: '', creative: '' })
const showPresetSave = reactive<Record<ProfileRole, boolean>>({ reasoning: false, creative: false })
const applyingPreset = ref<ProfileRole | null>(null)
const savingPreset = ref(false)
/** 删除二次确认：首点进入待确认态（按钮变红），3.5s 未复点自动解除 */
const armedDeleteRole = ref<ProfileRole | null>(null)
let armDeleteTimer: ReturnType<typeof setTimeout> | undefined

function presetLabel(p: ModelPresetItem): string {
  const suffix = p.source === 'auto' ? '（自动存档）' : ''
  return `${p.name}${suffix} · ${p.model || '未命名模型'}`
}

async function loadPresets() {
  try {
    presets.value = (await systemApi.getModelPresets()).presets
  } catch {
    /* 预设池加载失败不阻塞设置面板（下拉置空，其余功能不受影响） */
  }
}

function applyRoleConfig(role: ProfileRole, p: ModelConfig['llm'][ProfileRole]) {
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

async function onApplyPreset(role: ProfileRole) {
  const id = presetSelection[role]
  if (!id || applyingPreset.value) return
  applyingPreset.value = role
  try {
    const res = await systemApi.applyModelPreset(id, role)
    // 只刷新被切的槽——另一槽未保存的表单改动不受牵连
    applyRoleConfig(role, res.config.llm[role])
    presets.value = res.presets
    showToast(
      `已切换「${res.applied.name}」→ ${ROLE_SHORT_LABELS[role]}` +
        (res.auto_captured ? `（旧配置已自动存档「${res.auto_captured}」）` : ''),
      'success'
    )
  } catch (error: any) {
    presetSelection[role] = ''
    showToast('切换失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    applyingPreset.value = null
  }
}

function openPresetSave(role: ProfileRole) {
  showPresetSave[role] = true
  // 预填当前模型名，多数情况一键即存；名字可改成「DeepSeek 主力」这类自己认的
  presetNameDraft[role] = profileForms[role].model.trim()
  if (armedDeleteRole.value === role) {
    armedDeleteRole.value = null
    clearTimeout(armDeleteTimer)
  }
}

function closePresetSave(role: ProfileRole) {
  showPresetSave[role] = false
  presetNameDraft[role] = ''
}

async function savePresetFor(role: ProfileRole) {
  if (savingPreset.value) return
  const name = presetNameDraft[role].trim()
  if (!name) {
    showToast('请先给这套配置起个名字', 'error')
    return
  }
  savingPreset.value = true
  try {
    const res = await systemApi.saveModelPreset({
      name,
      copy_from_role: role,
      model: profileForms[role].model,
      base_url: profileForms[role].base_url,
      enabled: profileForms[role].enabled,
      effort: profileForms[role].effort,
      // Key 框留空（保持不变语义）时由服务端取槽内已存 Key——明文不经前端
      api_key: profileForms[role].api_key || undefined,
    })
    presets.value = res.presets
    closePresetSave(role)
    showToast(`预设「${name}」已保存${res.overwrote ? '（同名覆盖）' : ''}`, 'success')
  } catch (error: any) {
    showToast('保存预设失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    savingPreset.value = false
  }
}

async function onDeletePreset(role: ProfileRole) {
  const id = presetSelection[role]
  if (!id) return
  if (armedDeleteRole.value !== role) {
    armedDeleteRole.value = role
    clearTimeout(armDeleteTimer)
    armDeleteTimer = setTimeout(() => { armedDeleteRole.value = null }, 3500)
    return
  }
  armedDeleteRole.value = null
  clearTimeout(armDeleteTimer)
  try {
    presets.value = (await systemApi.deleteModelPreset(id)).presets
    // 两槽共用一个池，别槽若正指着被删条目一并复位
    for (const r of profileRoles) {
      if (presetSelection[r] === id) presetSelection[r] = ''
    }
    showToast('预设已删除', 'success')
  } catch (error: any) {
    showToast('删除失败: ' + (error.message || '未知错误'), 'error')
  }
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
    return '⚠ 该模型名已于 2026-07-24 弃用，请换 deepseek-flash'
  }
  if (b.includes('deepseek') && m === 'deepseek-v4-pro') {
    return '⚠ 09-14 12:00 起该模型将路由到 V4.1 Flash 并按其计费（V4.1 Pro 上线前），建议直接换 deepseek-flash'
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
    applyRoleConfig(role, config.llm[role])
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
    loadPresets()
    testResult.value = null
    deaiTestResult.value = null
    for (const role of profileRoles) {
      presetSelection[role] = ''
      showPresetSave[role] = false
      presetNameDraft[role] = ''
    }
    armedDeleteRole.value = null
    clearTimeout(armDeleteTimer)
  }
})
</script>

<template>
  <ModalShell
    v-if="visible"
    title="模型与 API"
    subtitle="AI 用什么模型写作、连什么服务——全局生效，与具体书籍无关"
    width="720px"
    @close="close"
  >
    <div v-if="loadError" class="error-banner">{{ loadError }}</div>
    <div v-else-if="loading" class="loading-hint">
      <Icon name="loader" :size="14" class="spin spin-reduced" />
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

          <!-- 快速切换：两槽共用预设池；选中即切换（服务端先把旧值自动存档，切换无损） -->
          <div class="preset-row">
            <select
              v-model="presetSelection[role]"
              class="preset-select"
              :disabled="!presets.length || applyingPreset === role"
              @change="onApplyPreset(role)"
            >
              <option value="" disabled>
                {{ presets.length ? '已存配置，选中即切换…' : '暂无已存配置' }}
              </option>
              <option v-for="p in presets" :key="p.id" :value="p.id">{{ presetLabel(p) }}</option>
            </select>
            <button
              type="button"
              class="preset-btn"
              :disabled="applyingPreset === role"
              title="把当前这套配置（含 Key）存为预设，随时切回"
              @click="openPresetSave(role)"
            >存为预设</button>
            <button
              type="button"
              class="preset-btn preset-del"
              :class="{ armed: armedDeleteRole === role }"
              :disabled="!presetSelection[role]"
              :title="presetSelection[role] ? '删除下拉中选中的预设（点两次确认）' : '先在下拉里选中要删的预设'"
              @click="onDeletePreset(role)"
            >{{ armedDeleteRole === role ? '确认删除？' : '删除' }}</button>
          </div>
          <div v-if="showPresetSave[role]" class="preset-save-row">
            <input
              v-model="presetNameDraft[role]"
              class="field field-input preset-name-input"
              placeholder="给这套配置起个名字，如：DeepSeek 主力"
              maxlength="80"
              @keyup.enter="savePresetFor(role)"
            />
            <button type="button" class="preset-btn preset-save-btn" :disabled="savingPreset" @click="savePresetFor(role)">
              <Icon v-if="savingPreset" name="loader" :size="12" class="spin spin-reduced" />
              保存
            </button>
            <button type="button" class="preset-btn" @click="closePresetSave(role)">取消</button>
          </div>

          <label class="field">
            <span class="field-label">厂商</span>
            <select
              v-model="vendorSelection[role]"
              class="field field-input"
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
              class="field field-input"
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
              class="field field-input"
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
              class="field field-input"
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
            <input v-model="embeddingForm.model" class="field field-input" placeholder="text-embedding-v2" />
          </label>

          <label v-if="!embeddingForm.follow_llm" class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="embeddingForm.api_key"
              type="password"
              class="field field-input"
              :placeholder="embeddingMeta.has_api_key
                ? `已保存 (${embeddingMeta.api_key_masked})，留空保持不变`
                : '输入 API Key'"
              autocomplete="new-password"
            />
          </label>

          <label class="field">
            <span class="field-label">向量维度</span>
            <input v-model.number="embeddingForm.dimensions" type="number" min="1" class="field field-input" />
          </label>
        </div>

        <label v-if="!embeddingForm.follow_llm" class="field">
          <span class="field-label">Base URL</span>
          <input
            v-model="embeddingForm.base_url"
            class="field field-input"
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
              class="field field-input"
              :placeholder="deaiMeta.effective_model || 'qwen3-4b-instruct-2507-…'"
            />
            <span class="field-sub-hint">百炼「部署管理」里的部署名；重新部署后会变，需回来更新。</span>
          </label>

          <label class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="deaiForm.api_key"
              type="password"
              class="field field-input"
              :placeholder="deaiMeta.has_api_key
                ? `已保存 (${deaiMeta.api_key_masked})，留空保持不变`
                : '阿里云百炼 DashScope API Key'"
              autocomplete="new-password"
            />
          </label>
        </div>

        <div class="deai-actions">
          <button type="button" class="btn-secondary" :disabled="deaiTesting" @click="runDeaiTest">
            <Icon v-if="deaiTesting" name="loader" :size="14" class="spin spin-reduced" />
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

      <!-- 网络代理（随 API 拆入：只为 LLM/向量出站服务） -->
      <section class="proxy-section">
        <div class="misc-title">网络代理</div>
        <label class="field-inline">
          <input v-model="proxyForm.enabled" type="checkbox" />
          <span>启用代理</span>
        </label>
        <input
          v-if="proxyForm.enabled"
          v-model="proxyForm.url"
          class="field field-input"
          placeholder="http://127.0.0.1:4780"
        />
      </section>

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
      <button class="btn-secondary footer-test btn-ghost" :disabled="testing || loading" @click="runTest">
        <Icon v-if="testing" name="loader" :size="14" class="spin spin-reduced" />
        <Icon v-else name="play" :size="14" />
        {{ testing ? '测试中...' : '连接测试' }}
      </button>
      <span class="footer-hint">保存后 LLM 与代理立即生效，无需重启</span>
      <button class="btn-primary btn-primary-instrument" :disabled="saving || loading" @click="save">
        <Icon v-if="saving" name="loader" :size="14" class="spin spin-reduced" />
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
  font-size: var(--text-sm);
  color: var(--text-muted);
  padding: 12px 0;
}

.error-banner {
  padding: 12px;
  font-size: var(--text-sm);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  border-radius: var(--radius-md);
}

/* ---------- 双模型并排 ---------- */

.profiles-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.profile-card {
  /* min-width:0 是布局护栏：预设下拉的长 option 文本有 ~230px 固有宽度，
     没有 1fr 轨道会被顶破 335px 均分，双列总宽溢出卡壳、右卡被截断（09-12 实测事故） */
  min-width: 0;
  padding: 12px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.profile-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 4px;
}

.profile-hint {
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.profile-hint-sub {
  margin-top: -6px;
  color: var(--warn);
}

/* ---------- 快速切换（模型配置预设） ---------- */

.preset-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.preset-select {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  outline: none;
  transition: border-color var(--dur-3) var(--ease-out);
}

.preset-select:focus {
  border-color: var(--accent-500);
}

.preset-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.preset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  font-size: var(--text-xs);
  white-space: nowrap;
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.preset-btn:hover:not(:disabled) {
  background: var(--accent-500);
  color: var(--bg-canvas);
}

.preset-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.preset-del.armed {
  color: var(--danger);
  border-color: var(--danger);
}

.preset-del.armed:hover:not(:disabled) {
  background: var(--danger);
  border-color: var(--danger);
  color: var(--bg-canvas);
}

.preset-save-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: -4px 0 10px;
}

.preset-name-input {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
}

.field {
  display: block;
  margin-bottom: 10px;
}

.field-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: 4px;
}

/* N1 §3.3：输入框收编 .field 工具类（field-input 仅作挂点保留，防悬空） */
.field-input {
  /* 皮肤由 .field 提供（模板挂 class="field field-input"） */
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
  font-size: var(--text-sm);
  color: var(--text-primary);
  cursor: pointer;
}

.flags-row .field-inline {
  margin-bottom: 0;
}

.effort-select {
  padding: 4px 6px;
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: color var(--dur-2) var(--ease-out), border-color var(--dur-2) var(--ease-out);
}

.advanced-toggle:hover {
  color: var(--text-secondary);
  border-color: var(--text-muted);
}

.advanced-caret {
  font-size: var(--text-xs);
}

.field-hint {
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.field-sub-hint {
  display: block;
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}

.follow-missing {
  color: var(--warn);
}

/* 模型级动态警示（弃用/下线/强制思考）——比普通提示醒目但不打断 */
.profile-warn {
  color: var(--warn);
}

.field-warning {
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--warn);
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.08);
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
}

.deai-result.success {
  border-color: color-mix(in srgb, var(--ok) 45%, transparent);
  background: color-mix(in srgb, var(--ok) 5%, transparent);
}

.deai-result.error {
  border-color: color-mix(in srgb, var(--danger) 45%, transparent);
  background: color-mix(in srgb, var(--danger) 5%, transparent);
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

/* ---------- 网络代理 ---------- */

.proxy-section {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.misc-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

/* ---------- 连接测试结果（紧凑条） ---------- */

.test-result {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
}

.test-result.success {
  border-color: color-mix(in srgb, var(--ok) 45%, transparent);
  background: color-mix(in srgb, var(--ok) 5%, transparent);
}

.test-result.error {
  border-color: color-mix(in srgb, var(--danger) 45%, transparent);
  background: color-mix(in srgb, var(--danger) 5%, transparent);
}

.test-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 600;
}

.test-result .status-icon {
  color: var(--accent-500);
}

.test-result.success .status-icon {
  color: var(--ok);
}

.test-result.error .status-icon {
  color: var(--danger);
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
/* N2 §3：footer 主/次钮收编仪器工具类（原 scoped 皮肤删除；折行病灶由工具类 white-space:nowrap 根治） */
.btn-primary,
.btn-secondary {
  /* 挂点：皮肤由 .btn-primary-instrument / .btn-ghost 提供 */
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
  font-size: var(--text-xs);
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
@container (max-width: 40rem) {
  .profiles-grid,
  .embedding-grid,
  .deai-grid {
    grid-template-columns: 1fr;
  }
}
</style>
