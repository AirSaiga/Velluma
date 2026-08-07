<script setup lang="ts">
/**
 * 渲染阶段「当前任务」焦点条（P1 新建）。
 *
 * 职责：把渲染阶段散落在 InspectorPanel 三处的引导（branch-choice-bar、stepping-bar、
 * StoryboardPanel 卡级动作）收敛成右栏顶部一个单一焦点。任何时刻只表达一件事，
 * 最多一个主按钮（或无）。
 *
 * 业务场景：作者点生成后跳到「节拍」tab，第一眼看到的就是这里——它告诉作者
 * "现在该做什么"：渲染前检查分镜卡、渲染中等待、就绪后二选一（接受/重写）、
 * 完成或有降级需复查。岔路门（选走向/补缺口）不在此——决策交互已上移
 * BranchDecisionPanel（顶部决策区），岔路态 currentTask 为 idle、本组件不渲染。
 * 改正文不再是指引面板——裁决窗口期左侧主编辑器直接可编辑，改动随接受定稿。
 *
 * 数据来源：session.currentTask（纯派生 computed，见 useGenerationSession.ts）。
 * 所有动作通过 emit 抛给父级 InspectorPanel 调 session 方法，本组件不直接调 services。
 */
import { computed } from 'vue'
import type { CurrentTask } from '../composables/useGenerationSession'
import Icon from '../../../components/Icon.vue'

const props = defineProps<{
  /** 来自 session.currentTask 的派生焦点数据 */
  task: CurrentTask
  /** 全局忙碌态（渲染中等），用于禁用按钮防重入 */
  busy?: boolean
  /** 重写面板是否展开（控制「重写本段」按钮的激活态与 chevron） */
  rewritePanelOpen?: boolean
  /** 作者是否已在主编辑器改过当前段（dirty 时显示「放弃改动」入口与已修改标） */
  authorDirty?: boolean
  /** 是否可回退（首段无快照时禁用回退按钮） */
  canBack?: boolean
}>()

const emit = defineEmits<{
  /** ① 接受本段/推进（advance 态主按钮；作者改过正文时父级自动走 lock_with_text） */
  (e: 'accept'): void
  /** ② 展开/收起重写面板 */
  (e: 'open-rewrite'): void
  /** 放弃作者在主编辑器的改动，还原 LLM 原文 */
  (e: 'revert-edit'): void
  /** ← 回到上一段（back action） */
  (e: 'back'): void
  /** ⏭ 跳过本段（skip action：本段不进入正文，直接渲染下一段） */
  (e: 'skip'): void
  /** ✕ 取消本次生成（裁决/渲染期唯一取消入口；父级调 session.cancel） */
  (e: 'cancel'): void
}>()

// 顶部状态图标（按 kind 选 Icon.vue 图标名）
const icon = computed(() => {
  switch (props.task.kind) {
    case 'edit-beats': return 'pencil'
    case 'rendering': return 'loader'
    case 'advance': return 'check-circle'
    case 'post-rescue': return 'exclamation-circle'
    case 'done': return 'check-badge'
    default: return 'information-circle'
  }
})

// 渲染中态图标是否旋转
const spinning = computed(() => props.task.kind === 'rendering')

// 主按钮是否禁用（忙碌时不让点接受，避免重入 advanceBeat）
const primaryDisabled = computed(() => props.busy && props.task.primary?.action === 'accept')

function onPrimary() {
  if (primaryDisabled.value) return
  // 仅剩 accept（edit-beats 的主按钮已移除：草稿在 StoryboardPanel 内部，
  // 焦点条无法取到，双入口曾致作者编辑静默丢失）
  emit('accept')
}
</script>

<template>
  <!-- idle 态不渲染焦点条（非渲染阶段，节拍 tab 会有自己的空态）。
       warn 橙色边框：post-rescue（完成但有降级/救援段）+ advance 降级态
       （本段渲染失败需作者处理），两类"需注意"状态视觉强化。 -->
  <div v-if="task.kind !== 'idle'" class="task" :class="{ warn: task.kind === 'post-rescue' || !!task.degraded }">
    <!-- 标题区 -->
    <div class="t-head">
      <Icon class="t-icon" :class="{ spin: spinning }" :name="icon" :size="22" />
      <div class="t-titles">
        <div class="t-title">{{ task.title }}</div>
        <div v-if="task.hint" class="t-sub">{{ task.hint }}</div>
      </div>
    </div>

    <!-- 按钮组（advance 态显示；edit-beats 态只显示主按钮）。
         降级态重组：把「重写本段」提为主操作（降级段正文为空、终稿会消失，
         应优先重写而非接受），「接受」降为弱化的 ghost 并明示后果。 -->
    <div v-if="(task.primary || task.kind === 'advance') && task.degraded" class="tri">
      <!-- ① 重写本段（降级态的主操作，让 AI 按新设定重试） -->
      <button
        class="btn btn-primary"
        :class="{ active: rewritePanelOpen }"
        :disabled="busy"
        @click="emit('open-rewrite')"
      >
        <span class="b-num">1</span>
        <span class="b-label">重写本段</span>
        <span class="b-hint">{{ rewritePanelOpen ? '收起' : '让 AI 重试' }}</span>
      </button>

      <!-- ② 接受（弱化：明示后果是这段不进正文，再进入下一段） -->
      <button
        v-if="task.primary"
        class="btn btn-ghost"
        :disabled="primaryDisabled"
        @click="onPrimary"
      >
        <span class="b-num">2</span>
        <span class="b-label">{{ task.primary.label }}</span>
      </button>
    </div>

    <!-- 非降级：原按钮顺序（接受为主） -->
    <div v-else-if="task.primary || task.kind === 'advance'" class="tri">
      <!-- ① 主按钮 -->
      <button
        v-if="task.primary"
        class="btn btn-primary"
        :disabled="primaryDisabled"
        @click="onPrimary"
      >
        <span class="b-num">1</span>
        <span class="b-label">{{ task.primary.label }}</span>
        <span v-if="task.primary.hint" class="b-hint">{{ task.primary.hint }}</span>
      </button>

      <!-- ② 重写本段 -->
      <button
        v-if="task.kind === 'advance'"
        class="btn btn-ghost"
        :class="{ active: rewritePanelOpen }"
        :disabled="busy"
        @click="emit('open-rewrite')"
      >
        <span class="b-num">2</span>
        <span class="b-label">重写本段</span>
        <span class="b-hint">{{ rewritePanelOpen ? '收起' : '改卡/走向' }}</span>
      </button>
    </div>

    <!-- Space 快捷键提示：裁决态下显示，避免作者不知道可以按空格推进。
         降级态隐藏——按 Space(accept) 会让空段进终稿后被过滤、默默丢段，
         不应再引导作者按 Space（降级引导事故）。 -->
    <div v-if="task.kind === 'advance' && !task.degraded" class="space-hint-row">
      <span class="space-key">Space</span>
      <span class="space-desc">{{
        task.isLast
          ? (authorDirty ? '采纳我的改动并完成本章' : '接受本段并完成本章')
          : (authorDirty ? '采纳我的改动并进入下一段' : '接受本段并进入下一段')
      }}</span>
    </div>

    <!-- 回退/跳过行（P3 back action；首段禁用回退；skip = 放弃本段不进正文；
         作者在主编辑器改过后，追加「放弃改动」出口还原 LLM 原文） -->
    <div v-if="task.kind === 'advance'" class="back-row">
      <button
        class="back-btn"
        :disabled="!canBack || busy"
        :title="canBack ? '解锁上一段，重新编辑或重写' : '已是第一段，无法回退'"
        @click="emit('back')"
      >
        ← 回到上一段
      </button>
      <span class="back-sep">·</span>
      <button
        class="back-btn skip"
        :disabled="busy"
        :title="'本段不进入正文，直接渲染下一段'"
        @click="emit('skip')"
      >
        跳过本段
      </button>
      <template v-if="authorDirty">
        <span class="back-sep">·</span>
        <button
          class="back-btn"
          :disabled="busy"
          :title="'放弃你在正文里的改动，还原为 AI 原文'"
          @click="emit('revert-edit')"
        >
          ↩ 放弃改动
        </button>
      </template>
    </div>

    <!-- 取消入口：裁决/渲染期间随时可放弃本次生成（此前底部状态条绑 generating，
         裁决态整个隐藏，后端 run 只能挂到 12h TTL——真实资源泄漏）。
         故意不随 busy 禁用：渲染卡死时这正是逃生口。 -->
    <div v-if="task.kind === 'advance' || task.kind === 'rendering'" class="cancel-row">
      <button class="back-btn cancel" @click="emit('cancel')">✕ 取消本次生成</button>
    </div>

    <!-- 重写面板 slot：父级 InspectorPanel 在 open-rewrite 时塞入改卡面板 -->
    <div v-if="task.kind === 'advance' && rewritePanelOpen" class="rewrite-slot">
      <slot name="rewrite" />
    </div>
  </div>
</template>

<style scoped>
.task {
  margin: 16px;
  padding: 18px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 14px;
  box-shadow: 0 4px 14px rgba(120, 100, 70, 0.05);
}
.task.warn {
  border-color: #fde68a;
}

/* 标题区 */
.t-head {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}
.t-icon {
  flex: 0 0 auto;
  color: var(--accent-500, #7c6aad);
}
.t-icon.spin {
  display: inline-block;
  animation: ctb-spin 0.8s linear infinite;
}
@keyframes ctb-spin {
  to { transform: rotate(360deg); }
}
.t-titles {
  flex: 1;
  min-width: 0;
}
.t-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
  line-height: 1.5;
}
.t-sub {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary, #6b6560);
  line-height: 1.6;
}

/* 三按钮组 */
.tri {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  text-align: left;
  transition: all 0.15s;
  border: 1px solid transparent;
}
.b-num {
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}
.b-label {
  flex: 1;
}
.b-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted, #a89e90);
}
.btn-primary {
  background: var(--accent-500, #7c6aad);
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600, #6d5dab);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
}
.btn-primary .b-num {
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
}
.btn-primary .b-hint {
  color: rgba(255, 255, 255, 0.7);
}
.btn-primary:active:not(:disabled) {
  transform: scale(0.98);
}
.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn-ghost {
  background: transparent;
  color: var(--text-secondary, #6b6560);
}
.btn-ghost .b-num {
  background: var(--bg-tertiary, #f0ece3);
  color: var(--text-secondary, #6b6560);
}
.btn-ghost:hover:not(:disabled),
.btn-ghost.active {
  background: var(--hover-bg, #eee9df);
  color: var(--text-primary, #2c2c2c);
}

/* 回退行 */
.back-row {
  display: flex;
  justify-content: flex-start;
  margin-top: 14px;
}
/* 取消行（独立于回退行：渲染态没有 back-row 也要可见） */
.cancel-row {
  display: flex;
  justify-content: flex-start;
  margin-top: 8px;
}
.back-btn.cancel {
  color: var(--text-muted, #a89e90);
}
.back-btn.cancel:hover {
  color: var(--danger-500, #c4533c);
  background: var(--danger-50, #fdf0ec);
}
.space-hint-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--bg-secondary, #faf8f4);
  border: 1px dashed var(--border-color, #e0dbd3);
}
.space-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e0dbd3);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary, #6b6560);
  box-shadow: 0 1px 0 rgba(0,0,0,0.06);
}
.space-desc {
  font-size: 13px;
  color: var(--text-muted, #a89e90);
}
.back-btn {
  font-size: 13px;
  color: var(--text-muted, #a89e90);
  padding: 5px 8px;
  border-radius: 6px;
}
.back-btn.skip {
  color: var(--danger-500, #c4533c);
}
.back-btn.skip:hover:not(:disabled) {
  background: var(--danger-50, #fdf0ec);
}
.back-sep {
  color: var(--border-color, #e0dbd3);
}

/* 重写面板 slot 容器 */
.rewrite-slot {
  margin-top: 12px;
}
</style>
