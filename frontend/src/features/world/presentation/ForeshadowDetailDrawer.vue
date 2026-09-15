<script setup lang="ts">
/**
 * 伏笔详情抽屉（M5：替代旧伏笔账本的编辑弹窗——就地编辑，失焦即存）。
 *
 * 三段式（复刻 EntityDetailDrawer 模式）：
 * ① 内容区（内容/类型 失焦即存）② 锚区（双时间锚 + 章锚 + hook_id——未锚定的可
 * 一键锚到游标时刻，锚后才上弧线带）③ 状态动作（回收=写游标时刻+closed / 废弃 /
 * 删除——删除进 undo 栈可 Ctrl+Z）。
 *
 * 轻量编辑不进 undo（与改名/拖锚同策略）；删除走 useWorld.deleteForeshadow（带 undo）。
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useToast } from '../../../composables/useToast'
import { useEscStack } from '../../../composables/useEscStack'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { formatTime } from '../engine/timeFormat'
import { vAutogrow } from './autogrow'

const props = defineProps<{ bookId: string; foreshadowId: string; canGoBack?: boolean }>()

const emit = defineEmits<{
  close: []
  /** 返回上一级（从图标栏面板钻入时才有上一级；由 WorldView 恢复来路面板） */
  back: []
}>()

const {
  foreshadows,
  currentTime,
  setCurrentTime,
  updateForeshadow,
  updateForeshadowTimes,
  resolveForeshadow,
  dropForeshadow,
  deleteForeshadow,
} = useWorld()
const { showToast } = useToast()

// Esc 分层关闭栈（00 期 §4.2）：挂载即入栈（一次 Esc 只关栈顶、焦点不在层内也生效），
// 卸载即出栈——替代根元素 @keydown.esc（旧路径焦点不在抽屉内时失效）
const escStack = useEscStack()
let escId: symbol | null = null
onMounted(() => { escId = escStack.push(() => emit('close'), 'foreshadow-detail-drawer') })
onUnmounted(() => { if (escId) escStack.remove(escId) })

const { show: showConfirm } = useConfirmDialog()

const foreshadow = computed(
  () => foreshadows.value.find((f) => f.id === props.foreshadowId) || null,
)

const TYPE_OPTS = [
  { value: 'foreshadow', label: '伏笔' },
  { value: 'callback', label: '呼应' },
  { value: 'twist', label: '反转' },
]
const STATUS_LABEL: Record<string, string> = { open: '埋设中', closed: '已回收', dropped: '已废弃' }

// ===== 内容区（失焦即存）=====

const contentDraft = ref('')
const chapterDraft = ref<number | null>(null)
const hookDraft = ref('')
watch(
  foreshadow,
  (f) => {
    contentDraft.value = f?.content || ''
    chapterDraft.value = f?.created_at_chapter ?? null
    hookDraft.value = f?.hook_id || ''
  },
  { immediate: true },
)

async function saveContent() {
  if (!foreshadow.value) return
  const c = contentDraft.value.trim()
  if (c && c !== foreshadow.value.content) {
    await updateForeshadow(props.bookId, foreshadow.value.id, { content: c })
    showToast('伏笔已更新', 'success')
  }
}

async function saveType(e: Event) {
  if (!foreshadow.value) return
  const v = (e.target as HTMLSelectElement).value
  if (v && v !== foreshadow.value.entry_type) {
    await updateForeshadow(props.bookId, foreshadow.value.id, { entry_type: v })
  }
}

async function saveChapter() {
  if (!foreshadow.value) return
  const v = chapterDraft.value && chapterDraft.value > 0 ? Math.floor(chapterDraft.value) : null
  if (v !== (foreshadow.value.created_at_chapter ?? null)) {
    await updateForeshadow(props.bookId, foreshadow.value.id, { created_at_chapter: v })
  }
}

async function saveHook() {
  if (!foreshadow.value) return
  const v = hookDraft.value.trim() || null
  if (v !== (foreshadow.value.hook_id ?? null)) {
    await updateForeshadow(props.bookId, foreshadow.value.id, { hook_id: v })
  }
}

// ===== 锚区 =====

/** 未锚定 → 锚到游标时刻（锚后才渲染上弧线带） */
async function anchorAtCursor() {
  if (!foreshadow.value) return
  await updateForeshadowTimes(props.bookId, foreshadow.value.id, {
    world_time_planted: currentTime.value,
  })
  showToast(`已锚定到 ${formatTime(currentTime.value)}`, 'success')
}

const isAuto = computed(() => {
  const s = foreshadow.value?.meta?.source
  return s === 'setup_graph_auto' || s === 'detonation_chain'
})
const evidence = computed(() => {
  const ev = foreshadow.value?.meta?.planted_in_text
  return typeof ev === 'string' && ev ? ev : null
})

// ===== 状态动作 =====

async function resolveHere() {
  if (!foreshadow.value) return
  await resolveForeshadow(props.bookId, foreshadow.value.id, currentTime.value)
  showToast(`已在 ${formatTime(currentTime.value)} 回收`, 'success')
}

/** 已回收/已废弃 → 重新打开（清回收锚，回到埋设中） */
async function reopen() {
  if (!foreshadow.value) return
  await updateForeshadowTimes(props.bookId, foreshadow.value.id, { world_time_resolved: null })
  await updateForeshadow(props.bookId, foreshadow.value.id, { status: 'open' })
  showToast('已重新打开', 'success')
}

async function drop() {
  if (!foreshadow.value) return
  await dropForeshadow(props.bookId, foreshadow.value.id)
  showToast('已废弃（不进生成上下文）', 'info')
}

async function remove() {
  if (!foreshadow.value) return
  const ok = await showConfirm({
    title: '删除伏笔',
    message: `确定删除这条伏笔吗？\n「${foreshadow.value.content.slice(0, 60)}」`,
    warning: '物理删除（可用 Ctrl+Z 撤销）。若只是不再需要，建议改为「废弃」。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteForeshadow(props.bookId, foreshadow.value.id)
  showToast('伏笔已删除', 'success')
  emit('close')
}
</script>

<template>
  <div v-if="foreshadow" class="fdd">
    <!-- 头部：状态 + 来源徽标 -->
    <div class="fdd-head">
      <button v-if="canGoBack" class="fdd-back" title="返回上一级" @click="emit('back')">
        <Icon name="arrow-left" :size="14" />
      </button>
      <span class="fdd-status" :class="foreshadow.status">{{ STATUS_LABEL[foreshadow.status] }}</span>
      <span v-if="isAuto" class="fdd-auto" title="由 AI 自动登记">AI 登记</span>
      <button class="fdd-close" title="关闭 (Esc)" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </div>

    <!-- 内容区 -->
    <div class="fdd-sec">
      <textarea
        v-model="contentDraft"
        v-autogrow
        class="fdd-content"
        rows="3"
        placeholder="这条伏笔是什么？"
        @blur="saveContent"
      ></textarea>
      <div class="fdd-row">
        <label class="fdd-lbl">类型</label>
        <select class="fdd-select" :value="foreshadow.entry_type" @change="saveType">
          <option v-for="t in TYPE_OPTS" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
      </div>
    </div>

    <!-- 锚区 -->
    <div class="fdd-sec">
      <div class="fdd-sec-title">锚</div>
      <div class="fdd-row">
        <label class="fdd-lbl">埋设时刻</label>
        <template v-if="foreshadow.world_time_planted != null">
          <span class="fdd-val">{{ formatTime(foreshadow.world_time_planted) }}</span>
          <button class="fdd-link" title="游标跳到埋设时刻" @click="setCurrentTime(foreshadow.world_time_planted!)">
            跳到
          </button>
        </template>
        <template v-else>
          <span class="fdd-val fdd-val--none">未锚定（不上弧线带）</span>
          <button
            class="fdd-link"
            :title="`锚定到游标当前时刻 ${formatTime(currentTime)}`"
            @click="anchorAtCursor"
          >
            锚到游标
          </button>
        </template>
      </div>
      <div class="fdd-row">
        <label class="fdd-lbl">回收时刻</label>
        <template v-if="foreshadow.world_time_resolved != null">
          <span class="fdd-val">{{ formatTime(foreshadow.world_time_resolved) }}</span>
          <button class="fdd-link" title="游标跳到回收时刻" @click="setCurrentTime(foreshadow.world_time_resolved!)">
            跳到
          </button>
        </template>
        <span v-else class="fdd-val fdd-val--none">—</span>
      </div>
      <div class="fdd-row">
        <label class="fdd-lbl">埋设章号</label>
        <input
          v-model.number="chapterDraft"
          class="fdd-input"
          type="number"
          min="1"
          placeholder="可选"
          @blur="saveChapter"
          @keyup.enter="($event.target as HTMLInputElement).blur()"
        />
      </div>
      <div class="fdd-row">
        <label class="fdd-lbl">钩子编号</label>
        <input
          v-model="hookDraft"
          class="fdd-input"
          placeholder="可选，如 hk-001"
          @blur="saveHook"
          @keyup.enter="($event.target as HTMLInputElement).blur()"
        />
      </div>
      <div v-if="evidence" class="fdd-evidence">
        <span class="fdd-lbl">证据</span>
        <span class="fdd-evidence-text">「{{ evidence }}」</span>
      </div>
    </div>

    <!-- 状态动作 -->
    <div class="fdd-actions">
      <button
        v-if="foreshadow.status === 'open'"
        class="fdd-act"
        :title="`在游标当前时刻 ${formatTime(currentTime)} 回收（写回收锚 + 状态改已回收）`"
        @click="resolveHere"
      >
        <Icon name="check" :size="13" />
        在此回收
      </button>
      <button v-else class="fdd-act" title="清回收锚，回到埋设中" @click="reopen">
        <Icon name="arrow-path" :size="13" />
        重新打开
      </button>
      <button
        v-if="foreshadow.status !== 'dropped'"
        class="fdd-act"
        title="废弃（保留账本记录，不进生成上下文）"
        @click="drop"
      >
        废弃
      </button>
      <button class="fdd-act fdd-act--danger" title="物理删除（Ctrl+Z 可撤销）" @click="remove">
        <Icon name="trash" :size="13" />
        删除
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 布局复刻 EntityDetailDrawer：absolute 浮于画布右上 */
.fdd {
  position: absolute;
  top: 48px;
  right: 58px; /* 避让 M6 图标栏（右缘 46px + 间隙） */
  bottom: 12px;
  width: 340px;
  z-index: 700;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: -4px 0 0 -1px var(--paper-edge), var(--shadow-lg); /* 04 §A2-3 纸叠影 */
  padding: 16px;
  overflow-y: auto;
  font-size: var(--text-sm);
}
.fdd::-webkit-scrollbar {
  width: 8px;
}
.fdd::-webkit-scrollbar-thumb {
  background: rgba(120, 95, 50, 0.22);
  border-radius: var(--radius-xs);
}
.fdd::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 95, 50, 0.38);
}
.fdd::-webkit-scrollbar-track {
  background: transparent;
}

.fdd-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fdd-status {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
}

.fdd-status.open {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  color: var(--warn);
}

.fdd-status.closed {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  color: var(--ok);
}

.fdd-status.dropped {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}

.fdd-auto {
  font-size: var(--text-xs);
  padding: 1px 5px;
  background: color-mix(in srgb, var(--accent-500) 12%, transparent);
  color: var(--accent-500);
  border-radius: var(--radius-xs);
}

.fdd-close {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}

.fdd-close:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}

/* 返回上一级（仅从图标栏面板钻入时出现，与关闭分权：← 回列表 / × 全关） */
.fdd-back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}

.fdd-back:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}

.fdd-sec {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.fdd-sec:first-of-type {
  margin-top: 10px;
  padding-top: 0;
  border-top: none;
}

.fdd-sec-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 8px;
  letter-spacing: 0.05em;
}

.fdd-content {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: 1.7;
  resize: none;
  max-height: 240px;
  outline: none;
}

.fdd-content:focus {
  border-color: var(--accent-500);
  box-shadow: var(--ring-soft);
}

.fdd-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.fdd-lbl {
  font-size: var(--text-xs);
  color: var(--text-muted);
  width: 52px;
  flex-shrink: 0;
}

.fdd-val {
  font-size: var(--text-xs);
  color: var(--text-primary);
  font-family: ui-monospace, monospace;
}

.fdd-val--none {
  font-family: inherit;
  color: var(--warn);
  font-size: var(--text-xs);
}

.fdd-link {
  margin-left: auto;
  font-size: var(--text-xs);
  padding: 2px 8px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
}

.fdd-link:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.fdd-input,
.fdd-select {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
}

.fdd-input:focus,
.fdd-select:focus {
  border-color: var(--accent-500);
  box-shadow: var(--ring-soft);
}

.fdd-evidence {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

.fdd-evidence-text {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-style: italic;
  line-height: 1.6;
}

.fdd-actions {
  display: flex;
  gap: 6px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.fdd-act {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}

.fdd-act:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.fdd-act--danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}
</style>
