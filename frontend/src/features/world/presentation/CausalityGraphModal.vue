<script setup lang="ts">
/**
 * 因果图谱模态（C1：旧 CanonGraph 降格迁入——只读查看器，只看不编）。
 *
 * 透镜而非画布：从「真相」账本底部 / 真相详情「关联」区唤起，随时合上。
 * 点节点右侧出信息条（真相摘要 + 跳回真相详情编辑），点边看边注；
 * 编辑不在图上——建边/改边回到真相条目（拍板 2026-08-17：保留为只读查看器）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import ModalShell from './ModalShell.vue'
import {
  useCanon,
  NODE_TYPE_COLORS,
  NODE_TYPE_LABELS,
  EDGE_TYPE_COLORS,
  EDGE_TYPE_LABELS,
  VISIBILITY_LABELS,
} from '../composables/useCanon'
import type { CanonEdge, CanonNode } from '../../../services/api/domain/canon.api'

const props = defineProps<{ bookId: string }>()

const emit = defineEmits<{
  close: []
  'open-truth': [nodeId: string]
}>()

const { nodes, edges } = useCanon()

type GraphFilter = 'all' | 'secret' | 'hook'
const filter = ref<GraphFilter>('all')
const FILTER_OPTS: { k: GraphFilter; l: string }[] = [
  { k: 'all', l: '全部' },
  { k: 'secret', l: '只看秘密' },
  { k: 'hook', l: '只看伏笔' },
]

const selectedNode = ref<CanonNode | null>(null)
const selectedEdge = ref<CanonEdge | null>(null)

function selectNode(n: CanonNode | null) {
  selectedNode.value = n
  selectedEdge.value = null
}
function selectEdge(e: CanonEdge | null) {
  selectedEdge.value = e
  selectedNode.value = null
}

const nodeById = (id: string) => nodes.value.find((n) => n.id === id)

const selectedEdgeEnds = computed(() => {
  if (!selectedEdge.value) return null
  const s = nodeById(selectedEdge.value.source_id)
  const t = nodeById(selectedEdge.value.target_id)
  return { s: s?.label || '?', t: t?.label || '?' }
})

const selectedNeighbors = computed(() => {
  if (!selectedNode.value) return 0
  const id = selectedNode.value.id
  return edges.value.filter((e) => e.source_id === id || e.target_id === id).length
})

function openTruth() {
  if (selectedNode.value) emit('open-truth', selectedNode.value.id)
}

// ===== Cytoscape（数据/过滤变化即整图重建——查看器无保位需求） =====
const containerRef = ref<HTMLDivElement | null>(null)
let cy: Core | null = null

const NODE_SIZE_MAP: Record<string, number> = {
  character: 58,
  event: 44,
  object: 40,
  place: 44,
  hook: 50,
}

function visibleGraph() {
  if (filter.value === 'secret') {
    const keep = nodes.value.filter((n) => n.visibility === 'private')
    const ids = new Set(keep.map((n) => n.id))
    return { nodes: keep, edges: edges.value.filter((e) => ids.has(e.source_id) && ids.has(e.target_id)) }
  }
  if (filter.value === 'hook') {
    const keep = nodes.value.filter((n) => n.type === 'hook')
    const ids = new Set(keep.map((n) => n.id))
    return { nodes: keep, edges: edges.value.filter((e) => ids.has(e.source_id) && ids.has(e.target_id)) }
  }
  return { nodes: nodes.value, edges: edges.value }
}

function buildElements(list: { nodes: CanonNode[]; edges: CanonEdge[] }): ElementDefinition[] {
  const els: ElementDefinition[] = []
  for (const node of list.nodes) {
    els.push({
      data: {
        id: node.id,
        label: node.label,
        type: node.type,
        visibility: node.visibility,
        size: NODE_SIZE_MAP[node.type] || 40,
        color: NODE_TYPE_COLORS[node.type] || '#6b7280',
        raw: node,
      },
    })
  }
  for (const edge of list.edges) {
    els.push({
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
  return els
}

function render() {
  if (!containerRef.value) return
  if (cy) {
    cy.destroy()
    cy = null
  }
  const list = visibleGraph()
  if (!list.nodes.length) return
  cy = cytoscape({
    container: containerRef.value,
    elements: buildElements(list),
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(color)',
          'width': 'data(size)',
          'height': 'data(size)',
          'label': 'data(label)',
          'color': 'var(--text-primary, #33302a)',
          'font-size': '11px',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 4,
          'text-wrap': 'ellipsis',
          'text-max-width': '80px',
          'border-width': 2,
          'border-color': '#ffffff',
        },
      },
      {
        // 朱描边 = 身上有秘密（与舆图名签朱点同一语义）
        selector: 'node[visibility = "private"]',
        style: { 'border-color': '#a63e2a', 'border-width': 3 },
      },
      {
        selector: 'node[visibility = "partial"]',
        style: { 'border-color': '#7c5faf', 'border-width': 3 },
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
        selector: 'edge[type = "hints"], edge[type = "before"]',
        style: { 'line-style': 'dashed' },
      },
      {
        selector: ':selected',
        style: { 'border-width': 4, 'border-color': '#b08d3e' },
      },
    ],
    layout: {
      name: 'cose',
      animate: true,
      animationDuration: 400,
      nodeRepulsion: 8000,
      idealEdgeLength: 100,
      nodeOverlap: 20,
      randomize: true,
    } as any,
    minZoom: 0.2,
    maxZoom: 3,
  })
  cy.on('tap', 'node', (evt) => selectNode(evt.target.data('raw') as CanonNode))
  cy.on('tap', 'edge', (evt) => selectEdge(evt.target.data('raw') as CanonEdge))
}

onMounted(async () => {
  await nextTick()
  render()
})
onBeforeUnmount(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})
watch([() => nodes.value, () => edges.value, filter], () => {
  selectNode(null)
  void nextTick(render)
})
</script>

<template>
  <ModalShell
    title="因果图谱"
    subtitle="只读透镜——编辑请回到真相条目 · 拖节点摆位 / 滚轮缩放"
    width="880px"
    @close="emit('close')"
  >
    <div class="cgm-wrap">
      <div class="cgm-canvas">
        <div class="cgm-filters">
          <button
            v-for="o in FILTER_OPTS"
            :key="o.k"
            class="cgm-chip"
            :class="{ active: filter === o.k }"
            @click="filter = o.k"
          >
            {{ o.l }}
          </button>
        </div>
        <div v-if="visibleGraph().nodes.length" ref="containerRef" class="cgm-cy"></div>
        <div v-else class="cgm-empty">
          {{ filter === 'all' ? '还没有真相条目——先在「真相」账本里记一条。' : '该过滤下没有条目。' }}
        </div>
        <div v-if="visibleGraph().nodes.length" class="cgm-legend">
          <span v-for="(c, t) in NODE_TYPE_COLORS" :key="t" class="cgm-lg-row">
            <span class="cgm-lg-dot" :style="{ background: c }"></span>{{ NODE_TYPE_LABELS[t] }}
          </span>
          <span class="cgm-lg-sep"></span>
          <span class="cgm-lg-row"><span class="cgm-lg-ring" style="border-color: #a63e2a"></span>秘密</span>
          <span class="cgm-lg-row"><span class="cgm-lg-ring" style="border-color: #7c5faf"></span>半露</span>
        </div>
      </div>

      <!-- 选中信息条 -->
      <div class="cgm-side">
        <template v-if="selectedNode">
          <span class="cgm-side-type" :style="{ background: NODE_TYPE_COLORS[selectedNode.type] || '#6b7280' }">
            {{ NODE_TYPE_LABELS[selectedNode.type] || selectedNode.type }}
          </span>
          <span class="cgm-side-vis" :class="`cgm-side-vis--${selectedNode.visibility}`">
            {{ VISIBILITY_LABELS[selectedNode.visibility] }}
          </span>
          <h4 class="cgm-side-name">{{ selectedNode.label }}</h4>
          <p v-if="selectedNode.canon_text" class="cgm-side-quote">{{ selectedNode.canon_text }}</p>
          <p class="cgm-side-nbr">一度邻居 {{ selectedNeighbors }} 条边</p>
          <button class="cgm-side-go" @click="openTruth">打开真相条目 ↗</button>
        </template>
        <template v-else-if="selectedEdge">
          <span class="cgm-side-type" :style="{ background: EDGE_TYPE_COLORS[selectedEdge.type] || '#9ca3af' }">
            {{ EDGE_TYPE_LABELS[selectedEdge.type] || selectedEdge.type }}
          </span>
          <h4 class="cgm-side-name cgm-side-name--sm">
            {{ selectedEdgeEnds?.s }} → {{ selectedEdgeEnds?.t }}
          </h4>
          <p class="cgm-side-nbr">强度 {{ selectedEdge.strength }} / 10</p>
          <p v-if="selectedEdge.note" class="cgm-side-quote">{{ selectedEdge.note }}</p>
        </template>
        <p v-else class="cgm-side-hint">点节点或边查看详情——建边、改边注请回真相条目编辑。</p>
      </div>
    </div>
  </ModalShell>
</template>

<style scoped>
.cgm-wrap {
  display: flex;
  height: 58vh;
  min-height: 380px;
  margin: -4px -6px 0;
}
.cgm-canvas {
  flex: 1;
  position: relative;
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  background: var(--bg-secondary);
  overflow: hidden;
}
.cgm-cy {
  position: absolute;
  inset: 0;
}
.cgm-filters {
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  z-index: 5;
  display: flex;
  gap: 0.25rem;
}
.cgm-chip {
  font-size: 0.625rem;
  padding: 0.1875rem 0.625rem;
  border-radius: 9999px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-muted);
  cursor: pointer;
}
.cgm-chip.active {
  background: var(--ink, #33302a);
  background: var(--text-primary);
  border-color: var(--text-primary);
  color: var(--bg-primary);
}
.cgm-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: 2rem;
  text-align: center;
}
.cgm-legend {
  position: absolute;
  bottom: 0.5rem;
  left: 0.5rem;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.3125rem 0.5rem;
  pointer-events: none;
}
.cgm-lg-row { display: inline-flex; align-items: center; gap: 0.25rem; }
.cgm-lg-dot { width: 0.5rem; height: 0.5rem; border-radius: 9999px; }
.cgm-lg-ring {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 9999px;
  border: 2px solid;
  box-sizing: border-box;
}
.cgm-lg-sep { width: 1px; height: 0.75rem; background: var(--border-color); }

.cgm-side {
  width: 210px;
  flex-shrink: 0;
  border-left: 1px solid var(--border-color);
  padding: 0.5rem 0.75rem 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  font-size: 0.75rem;
}
.cgm-side-type {
  align-self: flex-start;
  font-size: 0.5625rem;
  color: #fff;
  border-radius: 0.1875rem;
  padding: 0.125rem 0.375rem;
}
.cgm-side-vis { font-size: 0.625rem; color: var(--text-muted); }
.cgm-side-vis--private { color: #a63e2a; }
.cgm-side-vis--partial { color: #7c5faf; }
.cgm-side-name {
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 1.0625rem;
  color: var(--text-primary);
}
.cgm-side-name--sm { font-size: 0.875rem; }
.cgm-side-quote {
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--text-secondary);
  background: rgba(166, 62, 42, 0.08);
  border-left: 2px solid #a63e2a;
  border-radius: 0 0.375rem 0.375rem 0;
  padding: 0.4375rem 0.5625rem;
}
.cgm-side-nbr { font-size: 0.6875rem; color: var(--text-muted); }
.cgm-side-go {
  margin-top: auto;
  padding: 0.4375rem 0;
  font-size: 0.75rem;
  font-family: inherit;
  border: 1px solid rgba(166, 62, 42, 0.5);
  border-radius: 0.4375rem;
  background: transparent;
  color: #a63e2a;
  cursor: pointer;
}
.cgm-side-go:hover { background: rgba(166, 62, 42, 0.08); }
.cgm-side-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.8;
}
</style>
