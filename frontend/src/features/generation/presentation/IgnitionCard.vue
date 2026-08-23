<script setup lang="ts">
/**
 * NLE-ADF 点火卡 → 复合谋篇卡（P1.4 M1，docs/chapter-planning-spine.md §3.1）。
 *
 * 显示时机（由 WorkspaceView 编排，不变）：章内容为空白 + 无生成进行中 + 无幽灵草稿。
 * 度优先的谋篇时刻：一句话意图（可空）+ 可选 AI 建议（预填不过目不落库），
 * 然后照旧「⚡ 写个开头 / 我自己写」——一个字不写直接开写也毫无亏欠（D-1/D-2）。
 * 采纳语法沿用幽灵草稿全家桶。
 */
import type { ChapterSpine, SpineSuggestion } from '../../../services/api/domain/adaptive.api'

defineProps<{
  hasOutline: boolean
  spine: ChapterSpine | null
  suggestions: SpineSuggestion | null
  suggesting: boolean
}>()

const emit = defineEmits<{
  /** 意图输入失焦 → 存（PATCH spine） */
  (e: 'update-intent', text: string): void
  /** 拉取 AI 谋篇建议（不落库） */
  (e: 'suggest'): void
  /** 收下建议（此刻才落库） */
  (e: 'adopt', part: 'intent' | 'anchors' | 'all'): void
  (e: 'discard-suggestions'): void
  /** 点击「写个开头」→ 触发点火生成 */
  (e: 'ignite'): void
  /** 点击「我自己写」→ 本章内关闭（切章重置） */
  (e: 'dismiss'): void
}>()
</script>

<template>
  <div class="ignition-card" @mousedown.prevent>
    <div class="ignition-card__title">本章还是白纸</div>
    <!-- 谋篇时刻（D-1：唯一「要求」是一句可空的意图） -->
    <textarea
      class="ignition-card__intent"
      rows="1"
      :value="spine?.intent?.text || ''"
      placeholder="一句话：这一章主要讲什么？（可空）"
      @change="(e) => emit('update-intent', (e.target as HTMLTextAreaElement).value)"
    ></textarea>
    <template v-if="suggestions">
      <div class="ignition-card__suggest">
        <div v-if="suggestions.intent" class="ignition-card__suggest-intent">{{ suggestions.intent }}</div>
        <div v-if="suggestions.anchors?.length" class="ignition-card__suggest-anchors">
          <span v-for="(a, i) in suggestions.anchors" :key="i">{{ a }}</span>
        </div>
        <div class="ignition-card__suggest-actions">
          <button class="ignition-card__btn ignition-card__btn--primary" @click="emit('adopt', 'all')">收下建议</button>
          <button class="ignition-card__btn" @click="emit('discard-suggestions')">不用</button>
        </div>
      </div>
    </template>
    <div v-else class="ignition-card__actions">
      <template v-if="hasOutline">
        <button class="ignition-card__btn ignition-card__btn--primary" @click="emit('ignite')">
          ⚡ 写个开头
        </button>
        <button class="ignition-card__btn" @click="emit('dismiss')">我自己写</button>
      </template>
      <template v-else>
        <button class="ignition-card__btn" @click="emit('dismiss')">我自己写</button>
      </template>
    </div>
    <div class="ignition-card__hint">
      <template v-if="hasOutline">生成的是幽灵草稿：Enter 采纳 · Esc 蒸发 · 采纳后随时可改</template>
      <template v-else>先在副驾「打算」页写两句大纲，就能让 AI 帮你开个头</template>
    </div>
    <button
      v-if="!suggestions"
      class="ignition-card__suggest-link"
      :disabled="suggesting"
      @click="emit('suggest')"
    >{{ suggesting ? '建议生成中…' : '✨ AI 帮我出出主意' }}</button>
  </div>
</template>

<style scoped>
/* 画布中央淡卡（与 Spark/Beat Dock 同族磨砂风格，Cyber-Parchment Dark 双主题） */
.ignition-card {
  position: absolute;
  left: 50%;
  top: 38%;
  transform: translate(-50%, -50%);
  z-index: 10;
  width: min(380px, 80%);
  border-radius: 12px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.08);
  padding: 18px 20px 14px;
  text-align: center;
  user-select: none;
}

:root.dark .ignition-card {
  background: rgba(30, 32, 37, 0.92);
  border-color: #2a2d35;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.3);
}

.ignition-card__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
}

/* 谋篇意图（复合卡新增）：一行衬线输入，失焦即存 */
.ignition-card__intent {
  width: 100%;
  margin-top: 10px;
  resize: none;
  text-align: left;
  border: none;
  border-bottom: 1px dashed var(--border-color, #e0dbd3);
  background: transparent;
  font-family: var(--font-heading, inherit);
  font-size: 13px;
  color: var(--text-primary, #2c2c2c);
  padding: 4px 2px;
  line-height: 1.5;
}
.ignition-card__intent:focus {
  outline: none;
  border-bottom-color: var(--accent-400, #9685c2);
}
.ignition-card__intent::placeholder {
  color: var(--text-muted, #a89e90);
}

.ignition-card__suggest {
  margin-top: 10px;
  padding: 10px;
  text-align: left;
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 8px;
  background: var(--bg-secondary, #faf8f4);
}
.ignition-card__suggest-intent {
  font-size: 12.5px;
  color: var(--text-primary, #2c2c2c);
  line-height: 1.5;
}
.ignition-card__suggest-anchors {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ignition-card__suggest-anchors span {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px dashed var(--border-color, #e0dbd3);
  border-radius: 999px;
  color: var(--text-secondary, #6b6560);
}
.ignition-card__suggest-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.ignition-card__actions {
  margin-top: 12px;
  display: flex;
  justify-content: center;
  gap: 8px;
}

.ignition-card__btn {
  padding: 6px 14px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  background: var(--bg-secondary, #faf8f4);
  color: var(--text-secondary, #6b6560);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.ignition-card__btn:hover {
  background: var(--hover-bg, #eee9df);
}

.ignition-card__btn--primary {
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
  color: #fff;
}

.ignition-card__btn--primary:hover {
  background: var(--accent-600, #6d5dab);
}

.ignition-card__hint {
  margin-top: 10px;
  font-size: 10.5px;
  color: var(--text-muted, #a89e90);
}

.ignition-card__suggest-link {
  margin-top: 6px;
  border: none;
  background: none;
  font-size: 11px;
  color: var(--accent-500, #7c6aad);
  cursor: pointer;
}
.ignition-card__suggest-link:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
