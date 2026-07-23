<script setup lang="ts">
/**
 * Canon 图谱可视化（Cytoscape.js，V4.0 新建）。
 *
 * 职责：
 * - 把节点/边渲染为 force-directed 图
 * - 节点点击 → emit('node-click')
 * - 边点击 → emit('edge-click')
 * - 节点颜色按 type 区分，边颜色按 type 区分
 * - 悬停高亮邻居（其他变灰）
 *
 * 设计依据：docs/generation-v4.0-canon.md §5.1
 * 技术选型依据：调研结论（自带 force layout + 图算法）
 */
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import type { CanonNode, CanonEdge } from '../../../services/api/domain/canon.api'
import { NODE_TYPE_COLORS, EDGE_TYPE_COLORS, NODE_TYPE_LABELS } from '../composables/useCanon'

const props = defineProps<{
  nodes: CanonNode[]
  edges: CanonEdge[]
}>()

const emit = defineEmits<{
  (e: 'node-click', node: CanonNode): void
  (e: 'edge-click', edge: CanonEdge): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let cy: Core | null = null

const NODE_SIZE_MAP: Record<string, number> = {
  character: 60,
  event: 45,
  object: 40,
  place: 45,
  hook: 50,
}

function buildElements(): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  for (const node of props.nodes) {
    elements.push({
      data: {
        id: node.id,
        label: node.label,
        type: node.type,
        visibility: node.visibility,
        canon_text: node.canon_text,
        size: NODE_SIZE_MAP[node.type] || 40,
        color: NODE_TYPE_COLORS[node.type] || '#6b7280',
        raw: node,
      },
    })
  }

  for (const edge of props.edges) {
    elements.push({
      data: {
        id: edge.id,
        source: edge.source_id,
        target: edge.target_id,
        type: edge.type,
        strength: edge.strength,
        color: EDGE_TYPE_COLORS[edge.type] || '#9ca3af',
        raw: edge,
      },
    })
  }

  return elements
}

function initGraph() {
  if (!containerRef.value) return

  cy = cytoscape({
    container: containerRef.value,
    elements: buildElements(),
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(color)',
          'width': 'data(size)',
          'height': 'data(size)',
          'label': 'data(label)',
          'color': '#1f2937',
          'font-size': '11px',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 4,
          'text-wrap': 'ellipsis',
          'text-max-width': '80px',
          'border-width': 2,
          'border-color': '#ffffff',
          'opacity': 1,
        },
      },
      {
        selector: 'node[visibility = "private"]',
        style: {
          'border-color': '#f59e0b',
          'border-width': 3,
        },
      },
      {
        selector: 'node[visibility = "partial"]',
        style: {
          'border-color': '#8b5cf6',
          'border-width': 3,
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 'mapData(strength, 1, 10, 1, 5)',
          'line-color': 'data(color)',
          'target-arrow-color': 'data(color)',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'opacity': 0.7,
        },
      },
      {
        selector: ':selected',
        style: {
          'border-width': 4,
          'border-color': '#3b82f6',
        },
      },
      {
        selector: '.faded',
        style: {
          'opacity': 0.15,
        },
      },
      {
        selector: '.highlighted',
        style: {
          'opacity': 1,
          'border-color': '#fbbf24',
          'border-width': 4,
        },
      },
    ],
    layout: {
      name: 'cose',
      animate: true,
      animationDuration: 500,
      nodeRepulsion: 8000,
      idealEdgeLength: 100,
      nodeOverlap: 20,
      randomize: true,
    } as any,
    minZoom: 0.2,
    maxZoom: 3,
  })

  // 事件
  cy.on('tap', 'node', (evt) => {
    const raw = evt.target.data('raw') as CanonNode
    if (raw) emit('node-click', raw)
  })

  cy.on('tap', 'edge', (evt) => {
    const raw = evt.target.data('raw') as CanonEdge
    if (raw) emit('edge-click', raw)
  })

  // 悬停高亮邻居
  cy.on('mouseover', 'node', (evt) => {
    if (!cy) return
    const node = evt.target
    const neighborhood = node.closedNeighborhood()
    cy.elements().difference(neighborhood).addClass('faded')
    neighborhood.addClass('highlighted')
  })

  cy.on('mouseout', 'node', () => {
    if (!cy) return
    cy.elements().removeClass('faded highlighted')
  })
}

function relayout() {
  if (!cy) return
  cy.elements().remove()
  cy.add(buildElements())
  cy.layout({
    name: 'cose',
    animate: true,
    animationDuration: 300,
    nodeRepulsion: 8000,
    idealEdgeLength: 100,
    randomize: false,
  } as any).run()
}

onMounted(() => {
  initGraph()
})

onBeforeUnmount(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})

// 数据变化时重新加载
watch(
  () => [props.nodes, props.edges],
  () => {
    if (cy) {
      relayout()
    } else {
      initGraph()
    }
  },
  { deep: true },
)

// 暴露布局切换方法给父组件
defineExpose({
  relayout: (name: string = 'cose') => {
    if (!cy) return
    cy.layout({ name, animate: true } as any).run()
  },
  fit: () => {
    if (cy) cy.fit(undefined, 50)
  },
})
</script>

<template>
  <div class="canon-graph-wrap">
    <!-- 空状态引导（无节点时显示，替代空 canvas） -->
    <div v-if="!nodes.length" class="empty-canvas">
      <div class="empty-icon">🗺️</div>
      <h3>脑中世界还是空的</h3>
      <p>Canon 是你脑中真相的图谱——作者私有设定、伏笔、人物关系。</p>
      <p class="empty-hint">点击上方按钮开始建立：</p>
      <ul class="empty-suggestions">
        <li><strong>+ 角色</strong>：主角、配角、反派（可标 private 隐藏实力）</li>
        <li><strong>+ 伏笔</strong>：埋下的钩子，预期回收章节</li>
        <li><strong>+ 事件</strong>：已发生的关键剧情</li>
        <li><strong>+ 关系</strong>：连接两个节点（因果/暗示/铺设/回收）</li>
      </ul>
      <p class="empty-tip">★ private 节点（橙色环）不会泄露到生成的正文，但会作为角色隐藏动机影响行为。</p>
    </div>

    <!-- 有节点时显示图谱 -->
    <div v-else ref="containerRef" class="cytoscape-container"></div>

    <div v-if="nodes.length" class="legend">
      <div class="legend-row" v-for="(color, type) in NODE_TYPE_COLORS" :key="type">
        <span class="dot" :style="{ background: color }"></span>
        <span>{{ (NODE_TYPE_LABELS as any)[type] }}</span>
      </div>
      <div class="legend-divider"></div>
      <div class="legend-row">
        <span class="ring" style="border-color: #f59e0b"></span>
        <span>private（橙色环）</span>
      </div>
      <div class="legend-row">
        <span class="ring" style="border-color: #8b5cf6"></span>
        <span>partial（紫色环）</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.canon-graph-wrap {
  position: relative;
  height: 100%;
  width: 100%;
}
.cytoscape-container {
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}

.empty-canvas {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  text-align: center;
  background: var(--bg-primary);
  border: 1px dashed var(--border-color);
  border-radius: 0.5rem;
  color: var(--text-secondary);
}
.empty-icon {
  font-size: 3rem;
  margin-bottom: 0.5rem;
  opacity: 0.6;
}
.empty-canvas h3 {
  font-size: 1.125rem;
  margin: 0 0 0.5rem;
  color: var(--text-primary);
}
.empty-canvas p {
  font-size: 0.8125rem;
  line-height: 1.5;
  margin: 0.25rem 0;
  max-width: 420px;
}
.empty-hint {
  margin-top: 1rem !important;
  font-weight: 500;
  color: var(--text-primary);
}
.empty-suggestions {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
  text-align: left;
  font-size: 0.75rem;
  line-height: 1.8;
  color: var(--text-secondary);
}
.empty-suggestions li::before {
  content: '·';
  margin-right: 0.375rem;
  color: var(--accent-500);
}
.empty-tip {
  margin-top: 1rem !important;
  padding: 0.5rem 0.75rem;
  background: #fef3c7;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  color: #92400e;
  max-width: 420px;
}
.legend {
  position: absolute;
  bottom: 1rem;
  left: 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.6875rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  pointer-events: none;
}
.legend-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.ring {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid;
  background: transparent;
  display: inline-block;
  box-sizing: border-box;
}
.legend-divider {
  height: 1px;
  background: var(--border-color);
  margin: 0.25rem 0;
}
</style>
