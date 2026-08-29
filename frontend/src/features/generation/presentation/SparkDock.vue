<script setup lang="ts">
/**
 * NLE-ADF 灵感悬浮舱（Spark Dock）——灵感提示 + 补写入口。
 *
 * 光标停顿 4s（段尾）或 Tab 唤起时，在光标下方 8px 淡入 3~4 个
 * 【镜头特写挂件】（"老烟的血手"/"咬平齿的管钳"）。作者吸附挂件 →
 * Space 微缝合（AI 基于挂件指引流式续写，幽灵草稿形态）→ Enter 锁死。
 *
 * 挂件来自后端 dock_generator 对 recent_text + projections + 设定(nutrients/
 * hard_constraints) 的 LLM 生发，不是角色名罗列，也不是抽象建议。
 *
 * 功能槽位两级层级（2026-08-29「不知所云」重构）：每张卡必须自解释
 * 「选这枚会发生什么」——主行=画面碎片，副行=后果短语（▸ 接着刚才那句往下写 /
 * ⚑ 往「节拍」那拍走的第一步 / ◆ 顺笔带出前情/暗示读者在等 / ○ 纯画面·不牵动剧情）。
 * 旧五向 direction 标签退役不上屏（分析面元数据）；「接着写」恒居首位。
 *
 * Sticky：缝合触发后舱不消失（连续吸附多件缝合）；Esc 关舱退出 sticky。
 */
import { computed } from 'vue'
import type { SparkPart } from '../composables/useSparkDock'
import {
  sparkDockVisible,
  sparkParts,
  attachedParts,
  attachSparkPart,
  sparkSelectedIndex,
} from '../composables/useSparkDock'
import { ghostActive } from '../composables/useGhostDraft'

defineProps<{
  /** 是否显示「多写几段」入口（仅 adaptive composing 态，由容器注入） */
  showBurstEntry?: boolean
}>()

const emit = defineEmits<{
  /** 点击「多写几段」→ 打开走向卡舱 */
  burstEntry: []
}>()

const visible = computed(() => sparkDockVisible.value || attachedParts.value.length > 0)

/** 槽位 → 功能符号（landing=▸ 承接 / toward_beat=⚑ 锚点语言 / echo=◆ / ambient=○） */
const SOURCE_SYMBOL: Record<NonNullable<SparkPart['source']>, string> = {
  landing: '▸',
  toward_beat: '⚑',
  echo: '◆',
  ambient: '○',
}

/** 无 note 槽位的固定副行（ambient 留白设计已废除——2026-08-29 二轮实测：
 * 没人知道「留白是信息」，看到的只是「这张卡连解释都没有」） */
const SOURCE_FALLBACK_NOTE: Partial<Record<NonNullable<SparkPart['source']>, string>> = {
  landing: '接着刚才那句往下写',
  ambient: '纯画面 · 不牵动剧情',
}

function noteOf(part: SparkPart): string {
  return part.note || SOURCE_FALLBACK_NOTE[part.source ?? 'ambient'] || ''
}

function symbolOf(part: SparkPart): string {
  return part.source ? SOURCE_SYMBOL[part.source] : '○'
}

function onPick(index: number) {
  attachSparkPart(index)
}

function onBurstEntry() {
  emit('burstEntry')
}
</script>

<template>
    <Transition name="spark-dock">
      <div
        v-if="visible && !ghostActive"
        class="spark-dock"
        @mousedown.prevent
      >
        <!-- 挂件栏（镜头特写 chips，数字键 1~4 吸附） -->
        <div v-if="sparkDockVisible" class="spark-dock__row">
          <button
            v-for="(part, i) in sparkParts"
            :key="part.key"
            class="spark-dock__chip"
            :class="{
              'spark-dock__chip--attached': attachedParts.some(p => p.key === part.key),
              'spark-dock__chip--selected': i === sparkSelectedIndex,
            }"
            :title="part.note ? `${part.text}\n${part.note}` : part.text"
            @click="onPick(i)"
          >
            <span class="spark-dock__num">{{ i + 1 }}</span>
            <span class="spark-dock__body">
              <span class="spark-dock__text">{{ part.text }}</span>
              <span v-if="noteOf(part)" class="spark-dock__note">
                <span class="spark-dock__note-sym">{{ symbolOf(part) }}</span>
                {{ noteOf(part) }}
              </span>
            </span>
          </button>
          <!-- 段落级连写入口：打开走向卡舱（仅 adaptive composing 态由容器注入显示） -->
          <button
            v-if="showBurstEntry"
            class="spark-dock__burst"
            title="选一个走向，AI 连写几段（Ctrl+Space）"
            @click="onBurstEntry"
          >多写几段 ▸</button>
          <!-- 后果可见（2026-08-29：作者必须知道选了会发生什么） -->
          <div v-if="!attachedParts.length" class="spark-dock__tips">
            选中后 Space：以这枚画面为引接着写约百字 · Esc 收起
          </div>
        </div>
        <!-- 意图吸附栏（已选挂件 + 操作提示） -->
        <div v-if="attachedParts.length" class="spark-dock__intent">
          <span class="spark-dock__intent-pin">📌</span>
          <span
            v-for="part in attachedParts"
            :key="part.key"
            class="spark-dock__picked"
          >
            <span v-if="symbolOf(part)" class="spark-dock__note-sym">{{ symbolOf(part) }}</span>
            {{ part.text }}
          </span>
          <span class="spark-dock__hint">Space 以画面为引接着写 · Esc 清空</span>
        </div>
      </div>
    </Transition>
</template>

<style scoped>
/* 磨砂玻璃浮窗（Cyber-Parchment Dark 双主题自适应） */
.spark-dock {
  /* 感知带内流式区块（不再 fixed 浮层）；竖排镜头碎片 */
  width: 100%;
  box-sizing: border-box;
  border-radius: 8px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
  padding: 6px;
  margin-bottom: 8px;
  user-select: none;
}

:root.dark .spark-dock {
  background: rgba(30, 32, 37, 0.92);
  border-color: #2a2d35;
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
}

.spark-dock__row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}

.spark-dock__chip {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  max-width: 100%;
  padding: 4px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-primary, #2c2c2c);
  font-size: 12.5px;
  line-height: 1.5;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.spark-dock__chip:hover {
  background: rgba(52, 211, 153, 0.1);
}

.spark-dock__chip--attached {
  border-color: rgba(52, 211, 153, 0.4);
  background: rgba(52, 211, 153, 0.08);
}
/* ↑↓ 浏览选中（纯视觉，不影响吸附） */
.spark-dock__chip--selected {
  border-color: var(--accent-500, #7c6aad);
  background: rgba(124, 106, 173, 0.1);
  box-shadow: 0 0 0 2px rgba(124, 106, 173, 0.15);
}

.spark-dock__num {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  margin-top: 2px;
  border-radius: 4px;
  background: var(--hover-bg, #eee9df);
  color: var(--text-muted, #a89e90);
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* 卡片主体：主行=画面碎片，副行=功能出处（2026-08-29 两级层级） */
.spark-dock__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.spark-dock__text {
  /* 碎片文字允许换行，完整显示 8-16 字内容（不截断） */
  word-break: break-word;
  white-space: normal;
}

/* 功能出处副行：10px 弱化灰——主行是唯一主角，副行只回答「选这枚会发生什么」 */
.spark-dock__note {
  display: flex;
  align-items: baseline;
  gap: 3px;
  font-size: 10px;
  line-height: 1.4;
  color: var(--text-muted, #a89e90);
  word-break: break-word;
  white-space: normal;
}

.spark-dock__note-sym {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--accent-500, #7c6aad);
}

/* 后果提示行（无吸附时显示——作者必须知道选了会发生什么） */
.spark-dock__tips {
  padding: 3px 2px 1px;
  font-size: 10px;
  line-height: 1.4;
  color: var(--text-muted, #a89e90);
  border-top: 1px dashed var(--border-color, #e0dbd3);
  margin-top: 2px;
}

.spark-dock__intent {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 4px;
  margin-top: 4px;
  border-top: 1px dashed var(--border-color, #e0dbd3);
}

.spark-dock__intent:first-child {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
}

.spark-dock__intent-pin {
  font-size: 11px;
}

.spark-dock__picked {
  padding: 1px 8px;
  border-radius: 10px;
  background: rgba(52, 211, 153, 0.12);
  color: #059669;
  font-size: 12px;
  white-space: nowrap;
}

:root.dark .spark-dock__picked {
  color: #34d399;
}

.spark-dock__hint {
  margin-left: auto;
  color: var(--text-muted, #a89e90);
  font-size: 11px;
}

/* 段落级连写入口按钮（走向卡舱） */
.spark-dock__burst {
  flex-shrink: 0;
  margin-top: 2px;
  padding: 4px 10px;
  border: 1px dashed rgba(124, 106, 173, 0.45);
  border-radius: 10px;
  background: transparent;
  color: var(--accent-500, #7c6aad);
  font-size: 11.5px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.spark-dock__burst:hover {
  background: rgba(124, 106, 173, 0.1);
  border-color: var(--accent-500, #7c6aad);
}

/* 淡入下滑（150ms） */
.spark-dock-enter-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.spark-dock-leave-active {
  transition: opacity 0.1s ease, transform 0.1s ease;
}
.spark-dock-enter-from,
.spark-dock-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
