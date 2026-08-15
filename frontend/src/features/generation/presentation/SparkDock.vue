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
 * Sticky：缝合触发后舱不消失（连续吸附多件缝合）；Esc 关舱退出 sticky。
 */
import { computed } from 'vue'
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
            :title="part.text"
            @click="onPick(i)"
          >
            <span class="spark-dock__num">{{ i + 1 }}</span>
            <span
              v-if="part.direction"
              class="spark-dock__dir"
              :class="`spark-dock__dir--${part.direction}`"
            >{{ part.direction }}</span>
            <span
              v-if="part.origin === 'expectation'"
              class="spark-dock__origin"
              title="这枚零件呼应了期待账本里读者正在等的事"
            >期待</span>
            <span class="spark-dock__icon">{{ part.icon }}</span>
            <span class="spark-dock__text">{{ part.text }}</span>
          </button>
          <!-- 段落级连写入口：打开走向卡舱（仅 adaptive composing 态由容器注入显示） -->
          <button
            v-if="showBurstEntry"
            class="spark-dock__burst"
            title="选一个走向，AI 连写几段（Ctrl+Space）"
            @click="onBurstEntry"
          >多写几段 ▸</button>
        </div>
        <!-- 意图吸附栏（已选挂件 + 操作提示） -->
        <div v-if="attachedParts.length" class="spark-dock__intent">
          <span class="spark-dock__intent-pin">📌</span>
          <span
            v-for="part in attachedParts"
            :key="part.key"
            class="spark-dock__picked"
          >
            <span
              v-if="part.direction"
              class="spark-dock__dir spark-dock__dir--inline"
              :class="`spark-dock__dir--${part.direction}`"
            >{{ part.direction }}</span>
            <span
              v-if="part.origin === 'expectation'"
              class="spark-dock__origin spark-dock__origin--inline"
            >期待</span>
            {{ part.icon }} {{ part.text }}
          </span>
          <span class="spark-dock__hint">Space 缝合 · Esc 清空</span>
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
  border-radius: 4px;
  background: var(--hover-bg, #eee9df);
  color: var(--text-muted, #a89e90);
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.spark-dock__dir {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
  color: #fff;
  line-height: 1.4;
}
.spark-dock__dir--inline {
  margin-right: 3px;
}
.spark-dock__dir--主线 { background: #6366f1; }
.spark-dock__dir--伏笔 { background: #34d399; }
.spark-dock__dir--刻画 { background: #f59e0b; }
.spark-dock__dir--环境 { background: #06b6d4; }
.spark-dock__dir--关系 { background: #f43f5e; }

/* 期待账本来源 tag（描边样式，与方向实色块区分——作者一眼识别零件出处） */
.spark-dock__origin {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 0 4px;
  border-radius: 3px;
  color: #8b5cf6;
  border: 1px solid #8b5cf6;
  line-height: 1.5;
}
.spark-dock__origin--inline {
  margin-right: 3px;
}

.spark-dock__icon {
  flex-shrink: 0;
  font-size: 12px;
}

.spark-dock__text {
  /* 碎片文字允许换行，完整显示 8-16 字内容（不截断） */
  word-break: break-word;
  white-space: normal;
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
