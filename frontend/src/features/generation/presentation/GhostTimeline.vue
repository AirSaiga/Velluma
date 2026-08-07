<script setup lang="ts">
/**
 * NLE-ADF 2.0 底栏幽灵时间线（Ghost Timeline）。
 *
 * 极淡的节点连线，实时反映本章由碎片缝合而成的节拍结构：
 *   ● = 已锁碎片（当前拍内可点击回拨到该碎片锁死瞬间）
 *   ◐ = 当前创作中的拍 / 渲染中的拍
 *   ○ = 估算的未来碎片（按拍 target_word_count ÷ 100 预算，写超了轴自然生长）
 * 节点模型与顶栏进度共用（ghostTimelineModel.ts）。
 *
 * 平时透明度极低（设计稿"幽灵时间线"），hover 提亮；点击仅当前拍 ● 生效
 * （跨已锁拍回拨走 back 动作链，由焦点条提供，v1 不在轴上开放）。
 */
import type { GenerationSession } from '../composables/useGenerationSession'
import { useTimelineModel } from '../composables/ghostTimelineModel'

const props = defineProps<{ session: GenerationSession }>()

const { nodes, lockedCount, totalCount, timelineVisible } = useTimelineModel(props.session)

function onNodeClick(node: { beatId: string; fragIndex: number }) {
  // 仅当前创作拍的已锁碎片可回拨（v1 边界；其余节点只读展示）
  if (node.fragIndex > 0) {
    props.session.scrubToFragment(node.beatId, node.fragIndex)
  }
}
</script>

<template>
  <div v-if="timelineVisible" class="ghost-timeline">
    <span class="ghost-timeline__line">───</span>
    <button
      v-for="node in nodes"
      :key="node.key"
      class="ghost-timeline__node"
      :class="[
        `ghost-timeline__node--${node.state}`,
        { 'ghost-timeline__node--clickable': node.fragIndex > 0 },
      ]"
      :title="node.fragIndex > 0 ? `回到第 ${node.fragIndex} 个碎片` : ''"
      @click="onNodeClick(node)"
    >{{ node.state === 'locked' ? '●' : node.state === 'active' ? '◐' : '○' }}</button>
    <span class="ghost-timeline__line">───</span>
    <span class="ghost-timeline__count">{{ lockedCount }}/{{ totalCount }}</span>
  </div>
</template>

<style scoped>
.ghost-timeline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 2px 12px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  user-select: none;
}

.ghost-timeline__line {
  color: var(--text-muted, #8b8f98);
  font-size: 10px;
  letter-spacing: -1px;
}

.ghost-timeline__node {
  background: none;
  border: none;
  padding: 0 2px;
  font-size: 10px;
  line-height: 1;
  cursor: default;
  color: var(--text-muted, #8b8f98);
  transition: transform 0.15s ease, color 0.3s ease;
}

/* 锁死点亮：碎片提交瞬间节点弹亮 */
.ghost-timeline__node--locked {
  color: #34d399;
  animation: ghost-node-pop 0.3s ease;
}

.ghost-timeline__node--active {
  color: #fbbf24;
  animation: ghost-timeline-pulse 2s ease-in-out infinite;
}

.ghost-timeline__node--clickable {
  cursor: pointer;
}

.ghost-timeline__node--clickable:hover {
  transform: scale(1.4);
}

.ghost-timeline__count {
  margin-left: 8px;
  font-size: 10px;
  color: var(--text-muted, #8b8f98);
  font-variant-numeric: tabular-nums;
}

@keyframes ghost-node-pop {
  0% { transform: scale(1.8); filter: brightness(1.6); }
  100% { transform: scale(1); filter: brightness(1); }
}

@keyframes ghost-timeline-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
</style>
