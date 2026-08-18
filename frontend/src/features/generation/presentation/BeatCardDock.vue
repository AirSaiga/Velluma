<script setup lang="ts">
/**
 * NLE-ADF 走向卡舱（Beat Card Dock）——段落级连写的方向选择器。
 *
 * Ctrl+Space（或卡片舱「多写几段」按钮）唤起，光标处竖排弹出：
 * 2-3 张走向卡（后端层 3 推测的一句话剧情走向）+ 末项「自由发挥」。
 * 数字键 1~4 / 点击选定 → 立即触发 burst 连写（幽灵草稿形态，Enter 收 / Esc 蒸发）。
 *
 * 与卡片舱的分工：卡片舱管句级（镜头碎片），走向卡舱管段落级（剧情走向）。
 */
import { computed } from 'vue'
import { beatDockVisible, beatDockPos, beatCards } from '../composables/useBeatDock'
import { spine, flashAnchor } from '../../workspace/composables/useChapterSpine'

// 谋篇锚点小签（P1.4 M2）：由 serves_anchor id 查当前脉络的锚点文本（无脉络/已删=空）
function anchorText(id: string): string {
  const a = (spine.value?.anchors || []).find((x) => x.id === id && x.status !== 'dropped')
  return a?.text || ''
}
import type { DirectionCard } from '../../../services/api/domain/adaptive.api'

const emit = defineEmits<{
  /** 选定走向卡（null = 自由发挥） */
  pick: [card: DirectionCard | null]
}>()

const style = computed(() => ({
  top: `${beatDockPos.value.top}px`,
  left: `${beatDockPos.value.left}px`,
}))

function onPick(card: DirectionCard | null) {
  emit('pick', card)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="beat-dock">
      <div
        v-if="beatDockVisible"
        class="beat-dock"
        :style="style"
        @mousedown.prevent
      >
        <div class="beat-dock__title">接下来几段往哪写？</div>

        <button
          v-for="(card, i) in beatCards"
          :key="i"
          class="beat-dock__card"
          :class="{ 'beat-dock__card--branch': card.is_branch }"
          @click="onPick(card)"
        >
          <span class="beat-dock__num">{{ i + 1 }}</span>
          <span class="beat-dock__body">
            <span class="beat-dock__event">
              <span v-if="card.is_branch" class="beat-dock__branch-mark" title="作者声明的岔路——选一个走向，即决此岔">⚡</span>
              {{ card.event }}
              <!-- 谋篇锚点小签（P1.4 M2 §3.3）：这条建议服务于作者的哪个锚点——可追溯 -->
              <span
                v-if="card.serves_anchor && anchorText(card.serves_anchor)"
                class="beat-dock__anchor-tag"
                :title="'服务于谋篇锚点：' + anchorText(card.serves_anchor)"
                @click.stop="flashAnchor(card.serves_anchor)"
              >⚑ {{ anchorText(card.serves_anchor) }}</span>
            </span>
            <span v-if="card.anchors?.length" class="beat-dock__anchors">
              焦点：{{ card.anchors.join('、') }}
            </span>
          </span>
        </button>

        <!-- 末项固定：自由发挥（不指定走向，顺语气连写） -->
        <button class="beat-dock__card beat-dock__card--free" @click="onPick(null)">
          <span class="beat-dock__num">{{ beatCards.length + 1 }}</span>
          <span class="beat-dock__body">
            <span class="beat-dock__event">✍ 自由发挥</span>
            <span class="beat-dock__anchors">顺着现在的语气往下写</span>
          </span>
        </button>

        <div class="beat-dock__hint">{{ beatCards.length + 1 }} 以内数字键选择 · Esc 关闭</div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 磨砂玻璃浮窗（与 Spark Dock 同族，Cyber-Parchment Dark 双主题自适应） */
.beat-dock {
  position: fixed;
  z-index: 90;
  width: min(420px, 80vw);
  border-radius: 8px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  padding: 8px;
  user-select: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

:root.dark .beat-dock {
  background: rgba(30, 32, 37, 0.92);
  border-color: #2a2d35;
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
}

.beat-dock__title {
  font-size: 11px;
  color: var(--text-muted, #a89e90);
  padding: 2px 6px;
}

.beat-dock__card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.beat-dock__card:hover {
  background: rgba(124, 106, 173, 0.1);
  border-color: rgba(124, 106, 173, 0.3);
}

/* 作者声明岔路（P1.4 M3）：硬提示——朱色描边+浅底，视觉权重区别日常柔性建议 */
.beat-dock__card--branch {
  border-color: #c2725a;
  background: rgba(194, 114, 90, 0.08);
}
.beat-dock__card--branch:hover {
  background: rgba(194, 114, 90, 0.16);
  border-color: #c2725a;
}
.beat-dock__branch-mark {
  color: #c2725a;
  font-size: 12px;
  margin-right: 2px;
}
/* 谋篇锚点小签（P1.4 M2）：这条建议服务于哪个锚点 */
.beat-dock__anchor-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 999px;
  font-size: 10px;
  color: var(--accent-500, #7c6aad);
  cursor: pointer;
  vertical-align: middle;
}

.beat-dock__card--free {
  border-top: 1px dashed var(--border-color, #e0dbd3);
  border-radius: 0 0 8px 8px;
}

.beat-dock__num {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border-radius: 4px;
  background: var(--hover-bg, #eee9df);
  color: var(--text-muted, #a89e90);
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.beat-dock__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.beat-dock__event {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-primary, #2c2c2c);
  word-break: break-word;
}

.beat-dock__anchors {
  font-size: 10.5px;
  color: var(--text-muted, #a89e90);
}

.beat-dock__hint {
  font-size: 10.5px;
  color: var(--text-muted, #a89e90);
  padding: 2px 6px 0;
}

/* 淡入下滑（150ms，与 Spark Dock 一致） */
.beat-dock-enter-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.beat-dock-leave-active {
  transition: opacity 0.1s ease, transform 0.1s ease;
}
.beat-dock-enter-from,
.beat-dock-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
