<script setup lang="ts">
/**
 * 模型槽位编辑表单（写作/分析两槽共用，ApiSettingsModal 2026-09 UX 重构子件）。
 *
 * form 按引用传入直接改（reactive 对象）；厂商提示与模型警示由父组件算好
 * 以字符串传入（判据逻辑不搬家）；vendorSelection 双向绑定（具名 defineModel）。
 * 类型 ProfileForm/ProfileRole 以 export type/interface 在 script setup 顶部导出
 * （项目先例 Toast.vue；vite-env.d.ts shim 下仅这种写法对消费方可见）。
 */
export type ProfileRole = 'reasoning' | 'creative'

export interface ProfileForm {
  model: string
  api_key: string // 留空表示保持不变（服务端仅返回掩码）
  base_url: string
  enabled: boolean
  effort: string
}

export interface ProfileMeta {
  has_api_key: boolean
  api_key_masked: string
  configured?: boolean
}

import { computed, ref, watch } from 'vue'
import Icon from '../Icon.vue'
import { useToast } from '../../composables/useToast'
import type { VendorCatalogEntry } from '../../services/api'

const props = defineProps<{
  form: ProfileForm
  meta: ProfileMeta
  role: ProfileRole
  vendorCatalog: VendorCatalogEntry[]
  /** 厂商能力提示（父组件 vendorNotes 算好传入） */
  notes: string[]
  /** 模型级动态警示（父组件 modelWarning 算好传入，空串不渲染） */
  warning: string
  savingPreset: boolean
  /** 父组件在预设保存成功后 +1，本组件据此收起内联命名行（失败不收起，同旧版语义） */
  presetSavedTick: number
}>()

/** 每槽位的厂商选择（'custom' = 自定义/其他，自由输入 base_url）；具名 model 与父级 v-model:vendor-selection 对应 */
const vendorSelection = defineModel<string>('vendorSelection', { required: true })

const emit = defineEmits<{
  /** 手选厂商：父级自动填推荐 base_url */
  vendorChange: []
  savePreset: [name: string]
}>()

const { showToast } = useToast()

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

const currentVendor = computed(() => props.vendorCatalog.find((v) => v.id === vendorSelection.value) || null)
const vendorModels = computed(() => currentVendor.value?.models || [])

// ============================================================
// 存为预设：内联命名行（旧版「下拉切换+存为预设+删除」三按钮行退役——
// 应用/删除移入预设库分区，这里只留存档入口）
// ============================================================

const showPresetSave = ref(false)
const presetNameDraft = ref('')

function openPresetSave() {
  showPresetSave.value = true
  // 预填当前模型名，多数情况一键即存；名字可改成「DeepSeek 主力」这类自己认的
  presetNameDraft.value = props.form.model.trim()
}

function closePresetSave() {
  showPresetSave.value = false
  presetNameDraft.value = ''
}

// 保存成功（savingPreset true→false 且父级已拨 tick）后收起命名行
watch(
  () => props.presetSavedTick,
  () => closePresetSave()
)

function onSavePreset() {
  const name = presetNameDraft.value.trim()
  if (!name) {
    showToast('请先给这套配置起个名字', 'error')
    return
  }
  emit('savePreset', name)
}
</script>

<template>
  <div class="slot-pane">
    <div class="pane-title">{{ ROLE_LABELS[role] }}</div>
    <div class="pane-hint">{{ ROLE_HINTS[role] }}</div>
    <div v-if="role === 'reasoning'" class="pane-hint pane-hint-sub">
      留空（模型名与 Key 均不填）则自动跟随写作模型。
    </div>

    <label class="field">
      <span class="field-label">厂商</span>
      <select v-model="vendorSelection" class="field field-input" @change="emit('vendorChange')">
        <option value="custom">自定义 / 其他</option>
        <option v-for="v in vendorCatalog" :key="v.id" :value="v.id">{{ v.label }}</option>
      </select>
    </label>

    <label class="field">
      <span class="field-label">模型</span>
      <input
        v-model="form.model"
        class="field field-input"
        :list="`model-options-${role}`"
        :placeholder="MODEL_PLACEHOLDERS[role]"
      />
      <datalist :id="`model-options-${role}`">
        <option v-for="m in vendorModels" :key="m.id" :value="m.id">{{ m.label }}——{{ m.note }}</option>
      </datalist>
    </label>

    <label class="field">
      <span class="field-label">API Key</span>
      <input
        v-model="form.api_key"
        type="password"
        class="field field-input"
        :placeholder="meta.has_api_key
          ? `已保存 (${meta.api_key_masked})，留空保持不变`
          : '输入 API Key'"
        autocomplete="new-password"
      />
    </label>

    <label class="field">
      <span class="field-label">Base URL</span>
      <input
        v-model="form.base_url"
        class="field field-input"
        placeholder="https://api.deepseek.com/v1"
      />
    </label>

    <div class="flags-row">
      <label class="field-inline">
        <input v-model="form.enabled" type="checkbox" />
        <span>深度思考（Reasoning）</span>
      </label>
      <select v-if="form.enabled" v-model="form.effort" class="effort-select">
        <option value="low">low</option>
        <option value="medium">medium</option>
        <option value="high">high</option>
        <option value="max">max</option>
      </select>
    </div>

    <!-- 厂商能力提示（目录静态）+ 模型级动态警示（弃用/下线/强制思考） -->
    <div v-for="n in notes" :key="n" class="field-sub-hint">{{ n }}</div>
    <div v-if="warning" class="field-sub-hint profile-warn">{{ warning }}</div>

    <div class="preset-save">
      <button v-if="!showPresetSave" type="button" class="preset-btn" @click="openPresetSave">存为预设</button>
      <div v-else class="preset-save-row">
        <input
          v-model="presetNameDraft"
          class="field field-input preset-name-input"
          placeholder="给这套配置起个名字，如：DeepSeek 主力"
          maxlength="80"
          @keyup.enter="onSavePreset"
        />
        <button type="button" class="preset-btn preset-save-btn" :disabled="savingPreset" @click="onSavePreset">
          <Icon v-if="savingPreset" name="loader" :size="12" class="spin spin-reduced" />
          保存
        </button>
        <button type="button" class="preset-btn" :disabled="savingPreset" @click="closePresetSave">取消</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

.pane-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.pane-hint {
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.pane-hint-sub {
  margin-top: -6px;
  color: var(--warn);
}

.flags-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
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
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  outline: none;
}

.field-sub-hint {
  display: block;
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}

/* 模型级动态警示（弃用/下线/强制思考）——比普通提示醒目但不打断 */
.profile-warn {
  color: var(--warn);
}

/* ---------- 存为预设（内联命名行） ---------- */

.preset-save {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--line-faint);
}

.preset-save-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.preset-name-input {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
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
