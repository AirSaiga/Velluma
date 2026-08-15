<script setup lang="ts">
/**
 * Canon 主视图（V4.0 新建）。
 *
 * 三个 tab：
 * - 图谱：Cytoscape 可视化（force-directed）
 * - 节点：节点列表 + 编辑表单
 * - 伏笔：悬空伏笔列表
 *
 * 设计依据：docs/generation-v4.0-canon.md §5
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useCanon, NODE_TYPE_LABELS, VISIBILITY_LABELS } from '../composables/useCanon'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useToast } from '../../../composables/useToast'
import type { CanonNode, CanonEdge, CanonNodeType } from '../../../services/api/domain/canon.api'
import CanonGraph from './CanonGraph.vue'
import NodeEditModal from '../presentation/NodeEditModal.vue'
import EdgeEditModal from '../presentation/EdgeEditModal.vue'

const route = useRoute()
const bookId = computed(() => route.params.bookId as string)

const canon = useCanon()
const { show: showConfirm } = useConfirmDialog()
const { showToast } = useToast()

const activeTab = ref<'graph' | 'nodes' | 'hooks'>('graph')

// 编辑弹窗
const editingNode = ref<CanonNode | null>(null)
const editingEdge = ref<CanonEdge | null>(null)
const showNodeModal = ref(false)
const showEdgeModal = ref(false)
const creatingType = ref<CanonNodeType | null>(null)

// 过滤
const filterType = ref<CanonNodeType | ''>('')
const filterVisibility = ref<'public' | 'private' | 'partial' | ''>('')

const filteredNodes = computed(() => {
  return canon.nodes.value.filter(n => {
    if (filterType.value && n.type !== filterType.value) return false
    if (filterVisibility.value && n.visibility !== filterVisibility.value) return false
    return true
  })
})

const hookNodes = computed(() => {
  return canon.nodes.value.filter(n => n.type === 'hook')
})

const openHooks = computed(() => {
  return hookNodes.value.filter(n => {
    const status = n.metadata?.status || 'open'
    return status === 'open'
  })
})

const privateCount = computed(() => canon.nodes.value.filter(n => n.visibility === 'private').length)
const publicCount = computed(() => canon.nodes.value.filter(n => n.visibility === 'public').length)

function openCreateNode(type: CanonNodeType) {
  editingNode.value = null
  creatingType.value = type
  showNodeModal.value = true
}

function openEditNode(node: CanonNode) {
  editingNode.value = node
  creatingType.value = null
  showNodeModal.value = true
}

function openCreateEdge() {
  editingEdge.value = null
  showEdgeModal.value = true
}

function openEditEdge(edge: CanonEdge) {
  editingEdge.value = edge
  showEdgeModal.value = true
}

async function handleDeleteNode(node: CanonNode) {
  const ok = await showConfirm({
    title: '删除节点',
    message: `删除节点 [${node.label}]？相连的边会一并删除。`,
    warning: '删除后不可恢复。',
  })
  if (!ok) return
  try {
    await canon.deleteNode(bookId.value, node.id)
  } catch (e: any) {
    showToast('删除节点失败：' + (e?.message || '未知错误'), 'error')
  }
}

async function handleDeleteEdge(edge: CanonEdge) {
  const ok = await showConfirm({ title: '删除边', message: '确定删除这条边吗？' })
  if (!ok) return
  try {
    await canon.deleteEdge(bookId.value, edge.id)
  } catch (e: any) {
    showToast('删除边失败：' + (e?.message || '未知错误'), 'error')
  }
}

onMounted(async () => {
  if (bookId.value) await canon.load(bookId.value)
})

watch(bookId, async (val) => {
  if (val) await canon.load(val)
})
</script>

<template>
  <div class="canon-view">
    <header class="canon-header">
      <div>
        <h1 class="canon-title">作者脑中世界（Canon）</h1>
        <p class="canon-subtitle">
          作者脑中的真相图谱 ·
          {{ canon.nodes.value.length }} 节点（公开 {{ publicCount }} / 私有 {{ privateCount }}） ·
          {{ canon.edges.value.length }} 边 ·
          {{ openHooks.length }} 个悬空伏笔
        </p>
      </div>
      <div class="canon-actions">
        <button class="btn-primary" @click="openCreateNode('character')">+ 角色</button>
        <button class="btn-secondary" @click="openCreateNode('event')">+ 事件</button>
        <button class="btn-secondary" @click="openCreateNode('hook')">+ 伏笔</button>
        <button class="btn-secondary" @click="openCreateNode('object')">+ 物件</button>
        <button class="btn-secondary" @click="openCreateNode('place')">+ 地点</button>
        <button class="btn-secondary" @click="openCreateEdge">+ 关系</button>
      </div>
    </header>

    <nav class="canon-tabs">
      <button :class="{ active: activeTab === 'graph' }" @click="activeTab = 'graph'">图谱</button>
      <button :class="{ active: activeTab === 'nodes' }" @click="activeTab = 'nodes'">节点列表</button>
      <button :class="{ active: activeTab === 'hooks' }" @click="activeTab = 'hooks'">
        悬空伏笔
        <span v-if="openHooks.length" class="badge">{{ openHooks.length }}</span>
      </button>
    </nav>

    <div v-if="canon.loading.value" class="canon-loading">加载中…</div>
    <div v-else-if="canon.error.value" class="canon-error">加载失败：{{ canon.error.value }}</div>

    <main v-else class="canon-main">
      <!-- 图谱 tab -->
      <div v-if="activeTab === 'graph'" class="tab-graph">
        <CanonGraph
          :nodes="canon.nodes.value"
          :edges="canon.edges.value"
          @node-click="openEditNode"
          @edge-click="openEditEdge"
        />
      </div>

      <!-- 节点列表 tab -->
      <div v-else-if="activeTab === 'nodes'" class="tab-nodes">
        <div class="filters">
          <select v-model="filterType">
            <option value="">全部类型</option>
            <option v-for="(label, key) in NODE_TYPE_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
          <select v-model="filterVisibility">
            <option value="">全部可见性</option>
            <option value="public">公开</option>
            <option value="private">私有</option>
            <option value="partial">部分</option>
          </select>
        </div>

        <div class="node-grid">
          <div
            v-for="node in filteredNodes"
            :key="node.id"
            class="node-card"
            :class="`type-${node.type}`"
            @click="openEditNode(node)"
          >
            <div class="node-card-head">
              <span class="node-type-tag" :class="`type-${node.type}`">{{ NODE_TYPE_LABELS[node.type] }}</span>
              <span class="node-vis-tag" :class="`vis-${node.visibility}`">{{ VISIBILITY_LABELS[node.visibility] }}</span>
            </div>
            <div class="node-label">{{ node.label }}</div>
            <div class="node-text">{{ node.canon_text || '（无描述）' }}</div>
            <div class="node-footer">
              <span v-if="node.type === 'hook'" class="hook-strength">
                强度 {{ node.metadata?.strength || '?' }}
              </span>
              <span v-if="node.expected_reveal_chapter" class="reveal-chapter">
                第 {{ node.expected_reveal_chapter }} 章揭示
              </span>
              <button class="btn-delete" @click.stop="handleDeleteNode(node)">删除</button>
            </div>
          </div>
          <div v-if="!filteredNodes.length" class="empty-state">
            还没有 Canon 节点。点击上方"+ 角色 / + 事件 / + 伏笔"开始建立你的脑中世界。
          </div>
        </div>
      </div>

      <!-- 悬空伏笔 tab -->
      <div v-else-if="activeTab === 'hooks'" class="tab-hooks">
        <div v-if="!openHooks.length" class="empty-state">没有悬空伏笔。</div>
        <div v-else class="hook-list">
          <div
            v-for="hook in openHooks"
            :key="hook.id"
            class="hook-card"
            @click="openEditNode(hook)"
          >
            <div class="hook-card-head">
              <span class="hook-strength-large">强度 {{ hook.metadata?.strength || '?' }}/10</span>
              <span class="hook-status">{{ hook.metadata?.status || 'open' }}</span>
            </div>
            <div class="hook-label">{{ hook.label }}</div>
            <div class="hook-text">{{ hook.canon_text }}</div>
            <div class="hook-meta">
              <span v-if="hook.appeared_in?.length">埋于第 {{ hook.appeared_in.join(',') }} 章</span>
              <span v-if="hook.expected_reveal_chapter">预期第 {{ hook.expected_reveal_chapter }} 章回收</span>
              <span v-if="hook.reveal_plan">计划：{{ hook.reveal_plan }}</span>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- 编辑弹窗 -->
    <NodeEditModal
      v-if="showNodeModal"
      :book-id="bookId"
      :node="editingNode"
      :default-type="creatingType || 'event'"
      @close="showNodeModal = false"
      @saved="showNodeModal = false"
    />
    <EdgeEditModal
      v-if="showEdgeModal"
      :book-id="bookId"
      :edge="editingEdge"
      :nodes="canon.nodes.value"
      @close="showEdgeModal = false"
      @saved="showEdgeModal = false"
    />
  </div>
</template>

<style scoped>
.canon-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
}
.canon-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.canon-title {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0;
}
.canon-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0.25rem 0 0;
}
.canon-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.btn-primary, .btn-secondary {
  padding: 0.375rem 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
}
.btn-primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-primary:hover { opacity: 0.9; }
.btn-secondary:hover { background: var(--hover-bg); }

.canon-tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.canon-tabs button {
  padding: 0.5rem 1rem;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.8125rem;
}
.canon-tabs button.active {
  color: var(--accent-500);
  border-bottom-color: var(--accent-500);
}
.badge {
  display: inline-block;
  margin-left: 0.25rem;
  padding: 0 0.375rem;
  background: var(--accent-500);
  color: white;
  border-radius: 999px;
  font-size: 0.625rem;
}

.canon-loading, .canon-error {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
}
.canon-error { color: #dc2626; }

.canon-main {
  flex: 1;
  overflow: auto;
  padding: 1.5rem;
}

.tab-graph {
  height: calc(100vh - 220px);
  min-height: 400px;
}

.filters {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.filters select {
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  background: var(--bg-primary);
  font-size: 0.75rem;
}

.node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.75rem;
}
.node-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
  border-left: 3px solid var(--text-muted);
}
.node-card:hover {
  border-color: var(--accent-500);
  transform: translateY(-1px);
}
.node-card.type-character { border-left-color: #4f46e5; }
.node-card.type-event { border-left-color: #0891b2; }
.node-card.type-object { border-left-color: #ca8a04; }
.node-card.type-place { border-left-color: #16a34a; }
.node-card.type-hook { border-left-color: #dc2626; }

.node-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.node-type-tag {
  font-size: 0.625rem;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  background: var(--hover-bg);
  color: var(--text-muted);
}
.node-type-tag.type-character { background: #e0e7ff; color: #4f46e5; }
.node-type-tag.type-event { background: #cffafe; color: #0891b2; }
.node-type-tag.type-object { background: #fef9c3; color: #ca8a04; }
.node-type-tag.type-place { background: #dcfce7; color: #16a34a; }
.node-type-tag.type-hook { background: #fee2e2; color: #dc2626; }
.node-vis-tag {
  font-size: 0.625rem;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
}
.node-vis-tag.vis-public { background: #f1f5f9; color: #475569; }
.node-vis-tag.vis-private { background: #fef3c7; color: #b45309; }
.node-vis-tag.vis-partial { background: #ede9fe; color: #6d28d9; }

.node-label {
  font-weight: 600;
  font-size: 0.9375rem;
  margin-bottom: 0.25rem;
}
.node-text {
  font-size: 0.75rem;
  color: var(--text-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.node-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.btn-delete {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #dc2626;
  font-size: 0.6875rem;
  cursor: pointer;
  padding: 0.125rem 0.375rem;
}
.btn-delete:hover { text-decoration: underline; }

.empty-state {
  grid-column: 1 / -1;
  padding: 3rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.875rem;
}

.hook-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-width: 800px;
}
.hook-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left: 4px solid #dc2626;
  border-radius: 0.5rem;
  padding: 0.875rem;
  cursor: pointer;
}
.hook-card:hover { border-color: var(--accent-500); }
.hook-card-head {
  display: flex;
  gap: 0.75rem;
  font-size: 0.75rem;
  margin-bottom: 0.5rem;
}
.hook-strength-large { color: #dc2626; font-weight: 600; }
.hook-status {
  padding: 0.125rem 0.375rem;
  background: #fee2e2;
  color: #dc2626;
  border-radius: 0.25rem;
  font-size: 0.625rem;
}
.hook-label {
  font-weight: 600;
  font-size: 1rem;
  margin-bottom: 0.25rem;
}
.hook-text {
  font-size: 0.8125rem;
  color: var(--text-primary);
  line-height: 1.5;
  margin-bottom: 0.5rem;
}
.hook-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
</style>
