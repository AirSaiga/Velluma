<script setup lang="ts">
/**
 * 模型价目表编辑模态（成本核算，2026-09-11）。
 *
 * 数据页 AI 消耗卡「按价算钱」的编辑面：价格按各厂商公布页自填
 * （元/百万 token），保存走 PUT /system/model-prices 整表覆写，立即生效。
 * 行集 = 在用模型（by_model，带 token 量让作者知道哪个重要）∪ 已配价
 * 但当前无调用的模型；删行 = 该模型回到未计价。
 * 非法行（名字空/输入输出价非正数）保存时丢弃——与后端清洗同判据。
 */
import { computed, onMounted, ref } from 'vue'
import ModalShell from '../../../components/ModalShell.vue'
import { useToast } from '../../../composables/useToast'
import { systemApi, type ModelPriceTable } from '../../../services/api/domain'
import type { ModelUsageEntry } from '../../../services/api/domain/usage.api'

const props = defineProps<{
  /** 在用模型（usage by_model：token 量/是否已配价——决定行集与提示） */
  models: ModelUsageEntry[]
}>()

const emit = defineEmits<{
  close: []
  /** 保存成功（宿主刷新用量数据，金额立即上屏） */
  saved: []
}>()

const { showToast } = useToast()

interface PriceRow {
  model: string
  input: string
  cached: string
  output: string
}

const rows = ref<PriceRow[]>([])
const loading = ref(true)
const saving = ref(false)

const tokensByModel = computed(() => {
  const map: Record<string, number> = {}
  for (const m of props.models) map[m.model] = m.total_tokens || 0
  return map
})

function toRow(model: string, entry?: { input?: number; cached_input?: number; output?: number }): PriceRow {
  return {
    model,
    input: entry?.input != null ? String(entry.input) : '',
    cached: entry?.cached_input != null ? String(entry.cached_input) : '',
    output: entry?.output != null ? String(entry.output) : '',
  }
}

onMounted(async () => {
  try {
    const { prices } = await systemApi.getModelPrices()
    const rowModels: string[] = []
    // 在用模型在前（作者先看到重要的），已配价但无调用的殿后
    for (const m of props.models) rowModels.push(m.model)
    for (const model of Object.keys(prices)) {
      if (!rowModels.includes(model)) rowModels.push(model)
    }
    rows.value = rowModels.map((m) => toRow(m, prices[m]))
  } catch (e: any) {
    showToast(`读取价目表失败：${e?.message || '未知错误'}`, 'error')
  } finally {
    loading.value = false
  }
})

function addRow() {
  rows.value.push({ model: '', input: '', cached: '', output: '' })
}

function removeRow(i: number) {
  rows.value.splice(i, 1)
}

function parsePrice(v: string): number | null {
  if (v.trim() === '') return null
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) return null
  return n
}

/** 与后端清洗同判据：input/output 必填非负、cached 可选；非法行丢弃 */
function buildTable(): ModelPriceTable {
  const table: ModelPriceTable = {}
  for (const r of rows.value) {
    const model = r.model.trim()
    const input = parsePrice(r.input)
    const output = parsePrice(r.output)
    if (!model || input == null || output == null) continue
    const cached = parsePrice(r.cached)
    table[model] = cached != null
      ? { input, cached_input: cached, output }
      : { input, output }
  }
  return table
}

const invalidCount = computed(() => {
  let bad = 0
  for (const r of rows.value) {
    const model = r.model.trim()
    if (!model && r.input.trim() === '' && r.output.trim() === '' && r.cached.trim() === '') continue
    if (!model || parsePrice(r.input) == null || parsePrice(r.output) == null) bad++
  }
  return bad
})

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await systemApi.updateModelPrices(buildTable())
    showToast('价目表已保存，用量金额立即生效', 'success')
    emit('saved')
    emit('close')
  } catch (e: any) {
    showToast(`保存失败：${e?.message || '未知错误'}`, 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <ModalShell
    title="模型价格"
    subtitle="按各厂商公布页填写（元 / 百万 token）——缓存价没查到就留空，按输入全价保守估算"
    width="520px"
    @close="!saving && emit('close')"
  >
    <div v-if="loading" class="ps-loading">读取价目表…</div>
    <template v-else>
      <div class="ps-head">
        <span class="ps-col-model">模型</span>
        <span class="ps-col-num">输入</span>
        <span class="ps-col-num">缓存命中</span>
        <span class="ps-col-num">输出</span>
        <span class="ps-col-op"></span>
      </div>
      <div v-for="(r, i) in rows" :key="i" class="ps-row">
        <div class="ps-cell-model">
          <input v-model="r.model" class="ps-input ps-input--model" placeholder="模型名" spellcheck="false" />
          <span v-if="tokensByModel[r.model.trim()]" class="ps-usage">
            {{ (tokensByModel[r.model.trim()] / 1000).toFixed(1) }}k token 在用
          </span>
        </div>
        <input v-model="r.input" class="ps-input ps-input--num" inputmode="decimal" placeholder="—" />
        <input v-model="r.cached" class="ps-input ps-input--num" inputmode="decimal" placeholder="留空=全价" />
        <input v-model="r.output" class="ps-input ps-input--num" inputmode="decimal" placeholder="—" />
        <button class="ps-del" title="删除此模型价格（回到未计价）" @click="removeRow(i)">×</button>
      </div>
      <button class="ps-add" @click="addRow">＋ 添加模型</button>
      <p v-if="invalidCount > 0" class="ps-warn">
        {{ invalidCount }} 行未填完整（模型名 + 输入/输出价必填）——保存时这些行会被丢弃。
      </p>
      <p class="ps-hint">
        价格各厂商公布页可查（如同一家输入 2 元/百万、缓存命中 0.2 元/百万）。
        这里只算 generation_runs 台账内的调用；deai 抛光与向量检索走独立通道，另计。
      </p>
    </template>

    <template #footer>
      <button class="ps-btn" :disabled="saving" @click="emit('close')">取消</button>
      <button class="ps-btn ps-btn--primary btn-primary-instrument" :disabled="saving || loading" @click="save">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.ps-loading {
  padding: 24px;
  text-align: center;
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.ps-head,
.ps-row {
  display: grid;
  grid-template-columns: 1fr 4.5rem 4.5rem 4.5rem 1.5rem;
  gap: 6px;
  align-items: center;
}

.ps-head {
  padding: 0 2px 4px;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.ps-col-num,
.ps-col-op {
  text-align: center;
}

.ps-row {
  margin-bottom: 6px;
}

.ps-cell-model {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ps-usage {
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding-left: 6px;
}

.ps-input {
  padding: 4px 6px;
  font-size: var(--text-xs);
  background: var(--bg-secondary);
  border: 1px solid var(--line);
  border-radius: var(--radius-xs);
  color: var(--text-primary);
  min-width: 0;
}

.ps-input--model {
  width: 100%;
}

.ps-input--num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.ps-input:focus {
  outline: none;
  border-color: var(--accent-500);
}

.ps-del {
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--text-base);
  line-height: 1;
}

.ps-del:hover {
  background: var(--state-hover);
  color: var(--danger);
}

.ps-add {
  margin-top: 2px;
  padding: 4px 8px;
  font-size: var(--text-xs);
  color: var(--accent-500);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-xs);
  cursor: pointer;
}

.ps-add:hover {
  border-color: var(--accent-500);
}

.ps-warn {
  margin: 8px 0 0;
  font-size: var(--text-xs);
  color: var(--warn);
}

.ps-hint {
  margin: 8px 0 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}

.ps-btn {
  padding: 5px 14px;
  font-size: var(--text-xs);
  background: var(--bg-canvas);
  color: var(--text-primary);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-xs);
  cursor: pointer;
}

.ps-btn--primary {
}

.ps-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
