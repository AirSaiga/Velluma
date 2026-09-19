<script setup lang="ts">
/**
 * 模型与 API 弹窗（2026-09-15 设置拆分：从旧「设置」大弹窗独立；
 * 2026-09 设置拆分后续：UX 重构为左侧导航式）。
 *
 * 只管「AI 用什么模型、连什么服务」：左栏六项导航（写作/分析模型、预设库、
 * 向量记忆、去 AI 味、网络代理，各带实时状态小字）+ 右栏单分区呈现（本地
 * activeSection 切换，一次只渲染当前分区，默认落「写作模型」）。编辑表单拆
 * components/api/ModelSlotPane.vue（双槽共用）、预设库拆
 * components/api/PresetLibraryPane.vue。全局生效、与书籍无关；每次打开重拉配置，
 * 保存后 LLM 与代理立即生效（向量维度变更需重启）。外观/通知已分设独立入口，
 * 不再混装于此。
 */
import { computed, reactive, ref, watch } from 'vue'
import ModalShell from './ModalShell.vue'
import ModelSlotPane from './api/ModelSlotPane.vue'
import PresetLibraryPane from './api/PresetLibraryPane.vue'
import type { ProfileRole, ProfileForm } from './api/ModelSlotPane.vue'
import { systemApi } from '../services/api'
import type { ModelConfig, ModelConfigUpdatePayload, VendorCatalogEntry, ModelPresetItem } from '../services/api'
import { useAppSettings } from '../composables/useAppSettings'
import { useToast } from '../composables/useToast'
import Icon from './Icon.vue'

const { apiVisible: visible, closeApi: close } = useAppSettings()
const { showToast } = useToast()

// ============================================================
// 分区导航（本地切换，一次只渲染当前分区）
// ============================================================

type SectionId = ProfileRole | 'presets' | 'embedding' | 'deai' | 'proxy'

const activeSection = ref<SectionId>('creative')

// ============================================================
// 表单状态
// ============================================================

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

const ROLE_SHORT_LABELS: Record<ProfileRole, string> = {
  reasoning: '分析模型',
  creative: '写作模型',
}

// ============================================================
// 模型配置预设（快速切换，2026-09-11）：切走前整套存档（含 Key），预设库分区一点切回；
// 服务端另有自动存档安全网——覆盖槽位连接时旧值不完整或已存档才会丢，正常切换永不丢
// ============================================================

const presets = ref<ModelPresetItem[]>([])
const applyingPreset = ref<ProfileRole | null>(null)
const savingPreset = ref(false)
/** 保存成功信号：拨 +1 通知对应槽位的 ModelSlotPane 收起内联命名行（失败不收起，同旧版） */
const presetSavedTick = reactive<Record<ProfileRole, number>>({ reasoning: 0, creative: 0 })

async function loadPresets() {
  try {
    presets.value = (await systemApi.getModelPresets()).presets
  } catch {
    /* 预设池加载失败不阻塞设置面板（预设库置空，其余功能不受影响） */
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

async function onApplyPreset(id: string, role: ProfileRole) {
  if (applyingPreset.value) return
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
    showToast('切换失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    applyingPreset.value = null
  }
}

async function savePresetFor(role: ProfileRole, name: string) {
  if (savingPreset.value) return
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
    presetSavedTick[role] += 1
    showToast(`预设「${name}」已保存${res.overwrote ? '（同名覆盖）' : ''}`, 'success')
  } catch (error: any) {
    showToast('保存预设失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    savingPreset.value = false
  }
}

async function onDeletePreset(id: string) {
  try {
    presets.value = (await systemApi.deleteModelPreset(id)).presets
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

// ============================================================
// 去 AI 味小模型（deai/ 子项目，实验）：卡片舱续写短稿上屏前的抛光
// ============================================================

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

// ============================================================
// 左栏导航状态行（实时反映当前表单/配置）
// ============================================================

const reasoningNavStatus = computed(() => {
  if (!profileForms.reasoning.model && !profileForms.reasoning.api_key && !profileMeta.reasoning.has_api_key) {
    return '跟随写作模型'
  }
  return profileForms.reasoning.model || '未配置'
})

const embeddingNavStatus = computed(() => {
  if (embeddingForm.follow_llm) {
    return embeddingInherited.has_api_key ? '已配置·跟随写作模型' : '跟随写作模型（缺 Key）'
  }
  if (embeddingMeta.has_api_key || embeddingForm.model) return '已配置'
  return '未配置（默认记忆流）'
})

const navItems = computed(() => [
  { id: 'creative' as SectionId, icon: 'pencil-square', title: '写作模型', status: profileForms.creative.model || '未配置' },
  { id: 'reasoning' as SectionId, icon: 'magnifying-glass', title: '分析模型', status: reasoningNavStatus.value },
  { id: 'presets' as SectionId, icon: 'inbox', title: '预设库', status: presets.value.length ? `${presets.value.length} 套已存` : '暂无' },
  { id: 'embedding' as SectionId, icon: 'link', title: '向量记忆', status: embeddingNavStatus.value },
  { id: 'deai' as SectionId, icon: 'wand', title: '去 AI 味', status: deaiForm.enabled ? '已启用' : '未启用' },
  { id: 'proxy' as SectionId, icon: 'settings', title: '网络代理', status: proxyForm.enabled ? '已启用' : '已关闭' },
])

// 每次打开弹窗重新拉取配置（本地后端，开销可忽略），并清掉上次测试结果、
// 分区回落「写作模型」（槽位内表单/预设命名行等子件状态随 v-if 卸载自动归零）
watch(visible, (v) => {
  if (v) {
    activeSection.value = 'creative'
    loadConfig()
    loadCatalog()
    loadPresets()
    testResult.value = null
    deaiTestResult.value = null
  }
})
</script>

<template>
  <ModalShell
    v-if="visible"
    title="模型与 API"
    subtitle="AI 用什么模型写作、连什么服务——全局生效，与具体书籍无关"
    width="880px"
    @close="close"
  >
    <div v-if="loadError" class="error-banner">{{ loadError }}</div>
    <div v-else-if="loading" class="loading-hint">
      <Icon name="loader" :size="14" class="spin spin-reduced" />
      加载配置中...
    </div>

    <div v-else class="api-layout">
      <!-- 左栏导航：图标 + 标题 + 一行状态小字 -->
      <nav class="api-nav">
        <button
          v-for="item in navItems"
          :key="item.id"
          type="button"
          class="api-nav-item"
          :class="{ active: activeSection === item.id }"
          @click="activeSection = item.id"
        >
          <Icon :name="item.icon" :size="16" class="api-nav-icon" />
          <span class="api-nav-text">
            <span class="api-nav-title">{{ item.title }}</span>
            <span class="api-nav-status">{{ item.status }}</span>
          </span>
        </button>
      </nav>

      <!-- 右栏：单分区呈现，独立滚动 -->
      <div class="api-content">
        <ModelSlotPane
          v-if="activeSection === 'creative'"
          v-model:vendor-selection="vendorSelection.creative"
          :form="profileForms.creative"
          :meta="profileMeta.creative"
          role="creative"
          :vendor-catalog="vendorCatalog"
          :notes="vendorNotes('creative')"
          :warning="modelWarning('creative')"
          :saving-preset="savingPreset"
          :preset-saved-tick="presetSavedTick.creative"
          @vendor-change="onVendorChange('creative')"
          @save-preset="(name: string) => savePresetFor('creative', name)"
        />
        <ModelSlotPane
          v-else-if="activeSection === 'reasoning'"
          v-model:vendor-selection="vendorSelection.reasoning"
          :form="profileForms.reasoning"
          :meta="profileMeta.reasoning"
          role="reasoning"
          :vendor-catalog="vendorCatalog"
          :notes="vendorNotes('reasoning')"
          :warning="modelWarning('reasoning')"
          :saving-preset="savingPreset"
          :preset-saved-tick="presetSavedTick.reasoning"
          @vendor-change="onVendorChange('reasoning')"
          @save-preset="(name: string) => savePresetFor('reasoning', name)"
        />

        <PresetLibraryPane
          v-else-if="activeSection === 'presets'"
          :presets="presets"
          :applying="applyingPreset"
          @apply="onApplyPreset"
          @remove="onDeletePreset"
        />

        <!-- 向量记忆（专业级：未配置时走结构化+词法默认记忆流） -->
        <section v-else-if="activeSection === 'embedding'" class="pane">
          <div class="pane-title">向量记忆</div>
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
        </section>

        <!-- 去 AI 味小模型（deai/ 子项目，实验）：卡片舱续写短稿上屏前的抛光 -->
        <section v-else-if="activeSection === 'deai'" class="pane">
          <div class="pane-title">实验：去 AI 味小模型（续写短稿抛光）</div>
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
        </section>

        <!-- 网络代理（随 API 拆入：只为 LLM/向量出站服务） -->
        <section v-else-if="activeSection === 'proxy'" class="pane">
          <div class="pane-title">网络代理</div>
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
      </div>
    </div>

    <template #footer>
      <div class="footer-stack">
        <!-- 连接测试结果条（渲染在按钮行上方） -->
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

        <div class="footer-row">
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
        </div>
      </div>
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

/* ---------- 两栏骨架：负 margin 吃掉 ms-body 的 16/18 padding，左栏贴边 ---------- */

.api-layout {
  display: flex;
  align-items: stretch;
  /* 与右栏固定高一致，内容短时导航栏也不塌 */
  min-height: min(560px, 62vh);
  margin: -16px -18px;
}

.api-nav {
  width: 190px;
  flex-shrink: 0;
  padding: 10px 8px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--line-faint);
}

.api-nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  margin-bottom: 2px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
  transition: background var(--dur-2) var(--ease-out);
}

.api-nav-item:hover {
  background: var(--state-hover);
}

.api-nav-item.active {
  background: color-mix(in srgb, var(--accent-500) 10%, transparent);
}

/* 左侧 2px 指示条 */
.api-nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 2px;
  background: var(--accent-500);
}

.api-nav-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.api-nav-item.active .api-nav-icon {
  color: var(--accent-500);
}

.api-nav-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.api-nav-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.api-nav-item.active .api-nav-title {
  font-weight: 600;
}

.api-nav-status {
  font-size: var(--text-xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.api-content {
  flex: 1;
  min-width: 0;
  height: min(560px, 62vh);
  overflow-y: auto;
  padding: 16px 18px 8px 20px;
}

/* ---------- 分区标题层级 ---------- */

.pane-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

/* ---------- 表单工具类（与 ModelSlotPane 局部同名，各管各的 scoped） ---------- */

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

.field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: var(--text-sm);
  color: var(--text-primary);
  cursor: pointer;
}

.field-sub-hint {
  display: block;
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}

.field-hint {
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-muted);
  padding: 0 2px 4px;
  margin-bottom: 8px;
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

.follow-toggle {
  margin: 4px 0 10px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.follow-missing {
  color: var(--warn);
}

.embedding-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 110px;
  gap: 10px;
}

.embedding-grid.follow {
  grid-template-columns: 1fr 110px;
}

/* ---------- 去 AI 味小模型（deai） ---------- */

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
  border: 1px solid var(--line-faint);
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

/* ---------- 连接测试结果（紧凑条，footer 内按钮行上方） ---------- */

.test-result {
  padding: 10px 12px;
  border: 1px solid var(--line-faint);
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

/* footer slot 内套一层 column 容器：测试结果条在按钮行上方 */
.footer-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.footer-row {
  display: flex;
  align-items: center;
  gap: 8px;
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

/* 窄屏（小窗口）时导航收缩为 56px 纯图标列 */
@container (max-width: 40rem) {
  .api-nav {
    width: 56px;
    padding: 10px 6px;
  }

  .api-nav-item {
    justify-content: center;
    padding: 10px 0;
  }

  .api-nav-text {
    display: none;
  }

  .embedding-grid,
  .deai-grid {
    grid-template-columns: 1fr;
  }
}
</style>
