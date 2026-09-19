<script setup lang="ts">
/**
 * 文风页「写作规矩」区（2026-09 白描封杀令收编批）。
 *
 * 系统质感契约（services/style/texture_contracts.py 唯一权威）的按书定制面：
 * - 系统规矩与作者口味分治：这是系统给 AI 立的写作纪律（保护性护栏），
 *   不是负面清单那种个人词条——所以可编辑但随时「恢复默认」；
 * - 编辑只改契约正文，「最高优先级」框定与病灶词自动查改仍由系统持有；
 * - 生效范围 = 续写幽灵（Space 断点缝合/顺势续写），其余生成各有专职。
 */
import { ref } from 'vue'
import type { TextureContractItem } from '../../../types'

const props = defineProps<{
  contracts: TextureContractItem[]
}>()

const emit = defineEmits<{
  (e: 'save', key: string, body: string): void
  (e: 'reset', key: string): void
}>()

const editingKey = ref<string | null>(null)
const draftBody = ref('')
const expanded = ref<Record<string, boolean>>({})
const busy = ref(false)

function startEdit(c: TextureContractItem) {
  editingKey.value = c.key
  draftBody.value = c.body
}

function cancelEdit() {
  editingKey.value = null
  draftBody.value = ''
}

function save() {
  if (!editingKey.value || !draftBody.value.trim() || busy.value) return
  busy.value = true
  emit('save', editingKey.value, draftBody.value)
  // busy 的复位责任在容器（成功回调 closeEdit、失败回调 unlock）；此处只防连点
}

function closeEdit() {
  busy.value = false
  editingKey.value = null
  draftBody.value = ''
}

/** 保存失败解锁：只复位 busy，保留编辑键与草稿供改后重试（容器 catch 调用）。 */
function unlock() {
  busy.value = false
}

/** 编辑态内「恢复系统默认文本」= 把默认全文填回草稿（还不是落库） */
function fillDefault(c: TextureContractItem) {
  draftBody.value = c.default_body
}

function toggleExpand(key: string) {
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

function modesLabel(c: TextureContractItem): string {
  // 消费侧当前只有 stitch/continue 两档；未知模式原样拼接，防前端版本漂移乱码
  const names: Record<string, string> = { stitch: '断点续写', continue: '顺势续写' }
  return c.modes.map(m => names[m] || m).join('、')
}

defineExpose({ closeEdit, unlock })
</script>

<template>
  <section id="style-sec-contracts" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">写作规矩</h2>
      <p class="sec-sub">
        系统给 AI 立的写作纪律——每次续写幽灵都会带着它上岗。可以按这本书的口味调整，
        病灶词的自动查改始终有效；「恢复默认」随时一键回到系统原文。
      </p>
    </header>

    <div
      v-for="c in contracts"
      :key="c.key"
      class="contract-card"
      :class="{ customized: !c.is_default }"
    >
      <div class="contract-head">
        <span class="contract-title">{{ c.title }}</span>
        <span class="contract-badge" :class="c.is_default ? 'badge-default' : 'badge-custom'">
          {{ c.is_default ? '系统默认' : '本书定制' }}
        </span>
        <span class="contract-scope">作用于：{{ modesLabel(c) }}</span>
      </div>

      <template v-if="editingKey !== c.key">
        <pre class="contract-body" :class="{ clamped: !expanded[c.key] }">{{ c.body }}</pre>
        <div class="contract-actions">
          <button class="btn-link" @click="toggleExpand(c.key)">
            {{ expanded[c.key] ? '收起' : '展开全文' }}
          </button>
          <span class="spacer" />
          <button
            v-if="!c.is_default"
            class="btn-ghost"
            title="放弃本书定制，恢复系统默认原文"
            @click="emit('reset', c.key)"
          >恢复默认</button>
          <button class="btn-primary" @click="startEdit(c)">编辑</button>
        </div>
      </template>

      <template v-else>
        <textarea
          v-model="draftBody"
          class="contract-editor"
          rows="14"
          spellcheck="false"
        />
        <div class="contract-actions">
          <button class="btn-link" @click="fillDefault(c)">填入系统默认文本</button>
          <span class="spacer" />
          <button class="btn-ghost" :disabled="busy" @click="cancelEdit">取消</button>
          <button
            class="btn-primary"
            :disabled="busy || !draftBody.trim()"
            @click="save"
          >{{ busy ? '保存中…' : '保存' }}</button>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
/* 2026-09-17 视觉归一：全量迁移 token 方言（docs/design/style-page-redesign.md §4.7） */
.style-section {
  margin-top: var(--space-6);
}
.sec-head {
  margin-bottom: var(--space-3);
}
/* 与全局 .sec-hint 同规格（模板历史类名 sec-sub，保留不改） */
.sec-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--text-secondary);
}
.contract-card {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.contract-card.customized {
  border-color: var(--warn);
}
.contract-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.contract-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}
.contract-badge {
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  border-radius: var(--radius-pill);
}
.badge-default {
  color: var(--text-secondary);
  background: var(--bg-tertiary);
}
.badge-custom {
  color: var(--warn);
  background: var(--warn-bg);
}
.contract-scope {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.contract-body {
  margin: 0;
  font-family: inherit;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
}
.contract-body.clamped {
  max-height: 96px;
  overflow: hidden;
}
.contract-editor {
  box-sizing: border-box;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--text-primary);
  background: var(--field-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  resize: vertical;
}
.contract-editor:focus-visible {
  border-color: var(--accent-400);
}
.contract-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.spacer {
  flex: 1;
}
.btn-link {
  min-height: var(--control-h-sm);
  padding: 0;
  font-size: var(--text-xs);
  color: var(--accent-500);
  background: none;
  border: none;
  cursor: pointer;
}
.btn-link:hover {
  text-decoration: underline;
}
.btn-ghost {
  min-height: var(--control-h-sm);
  padding: 0 var(--control-px);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-ghost:hover:not(:disabled) {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.btn-ghost:disabled {
  opacity: 0.5;
  cursor: default;
}
.btn-primary {
  min-height: var(--control-h-sm);
  padding: 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
