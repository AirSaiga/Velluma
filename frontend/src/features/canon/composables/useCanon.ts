/**
 * Canon 状态管理（V4.0 新建）。
 *
 * 职责：
 * - 加载/缓存整书图谱
 * - 节点/边 CRUD（自动刷新缓存）
 * - 一致性检查、连锁分析、自动提取
 *
 * 设计依据：docs/generation-v4.0-canon.md §5
 */
import { ref, type Ref } from 'vue'
import {
  canonApi,
  type CanonNode,
  type CanonEdge,
  type CanonGraph,
  type ConsistencyCheckResult,
  type ImpactAnalysisResult,
  type CanonExtractionResult,
  type CanonNodeCreate,
  type CanonNodeUpdate,
  type CanonEdgeCreate,
  type CanonEdgeUpdate,
  type CanonNodeType,
  type CanonVisibility,
} from '../../../services/api/domain/canon.api'

export interface UseCanon {
  nodes: Ref<CanonNode[]>
  edges: Ref<CanonEdge[]>
  loading: Ref<boolean>
  error: Ref<string | null>
  // 控制
  load: (bookId: string) => Promise<void>
  refresh: () => Promise<void>
  // 节点 CRUD
  createNode: (bookId: string, data: CanonNodeCreate) => Promise<CanonNode>
  updateNode: (bookId: string, nodeId: string, data: CanonNodeUpdate) => Promise<CanonNode>
  deleteNode: (bookId: string, nodeId: string) => Promise<void>
  // 边 CRUD
  createEdge: (bookId: string, data: CanonEdgeCreate) => Promise<CanonEdge>
  updateEdge: (bookId: string, edgeId: string, data: CanonEdgeUpdate) => Promise<CanonEdge>
  deleteEdge: (bookId: string, edgeId: string) => Promise<void>
  // 分析
  checkConsistency: (bookId: string, text: string) => Promise<ConsistencyCheckResult>
  analyzeImpact: (bookId: string, nodeId: string) => Promise<ImpactAnalysisResult>
  extract: (bookId: string, chapterId: string, autoCommit?: boolean) => Promise<CanonExtractionResult>
}

export function useCanon(): UseCanon {
  const nodes = ref<CanonNode[]>([])
  const edges = ref<CanonEdge[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  let currentBookId: string | null = null

  async function load(bookId: string) {
    currentBookId = bookId
    await refresh()
  }

  async function refresh() {
    if (!currentBookId) return
    loading.value = true
    error.value = null
    try {
      const graph: CanonGraph = await canonApi.getGraph(currentBookId)
      nodes.value = graph.nodes || []
      edges.value = graph.edges || []
    } catch (e: any) {
      error.value = e.message || '加载失败'
      console.warn('[useCanon] load failed:', e)
    } finally {
      loading.value = false
    }
  }

  async function createNode(bookId: string, data: CanonNodeCreate): Promise<CanonNode> {
    const node = await canonApi.createNode(bookId, data)
    await refresh()
    return node
  }

  async function updateNode(bookId: string, nodeId: string, data: CanonNodeUpdate): Promise<CanonNode> {
    const node = await canonApi.updateNode(bookId, nodeId, data)
    await refresh()
    return node
  }

  async function deleteNode(bookId: string, nodeId: string): Promise<void> {
    await canonApi.deleteNode(bookId, nodeId)
    await refresh()
  }

  async function createEdge(bookId: string, data: CanonEdgeCreate): Promise<CanonEdge> {
    const edge = await canonApi.createEdge(bookId, data)
    await refresh()
    return edge
  }

  async function updateEdge(bookId: string, edgeId: string, data: CanonEdgeUpdate): Promise<CanonEdge> {
    const edge = await canonApi.updateEdge(bookId, edgeId, data)
    await refresh()
    return edge
  }

  async function deleteEdge(bookId: string, edgeId: string): Promise<void> {
    await canonApi.deleteEdge(bookId, edgeId)
    await refresh()
  }

  async function checkConsistency(bookId: string, text: string): Promise<ConsistencyCheckResult> {
    return await canonApi.checkConsistency(bookId, text)
  }

  async function analyzeImpact(bookId: string, nodeId: string): Promise<ImpactAnalysisResult> {
    return await canonApi.analyzeImpact(bookId, nodeId)
  }

  async function extract(bookId: string, chapterId: string, autoCommit: boolean = false): Promise<CanonExtractionResult> {
    const result = await canonApi.extract(bookId, chapterId, autoCommit)
    if (autoCommit) await refresh()
    return result
  }

  return {
    nodes,
    edges,
    loading,
    error,
    load,
    refresh,
    createNode,
    updateNode,
    deleteNode,
    createEdge,
    updateEdge,
    deleteEdge,
    checkConsistency,
    analyzeImpact,
    extract,
  }
}

// ============================================================
// 常量（UI 显示用）
// ============================================================

export const NODE_TYPE_LABELS: Record<CanonNodeType, string> = {
  character: '角色',
  event: '事件',
  object: '物件',
  place: '地点',
  hook: '伏笔',
}

export const NODE_TYPE_COLORS: Record<CanonNodeType, string> = {
  character: '#4f46e5', // 靛蓝
  event: '#0891b2',     // 青蓝
  object: '#ca8a04',    // 土黄
  place: '#16a34a',     // 绿
  hook: '#dc2626',      // 红
}

export const EDGE_TYPE_LABELS: Record<string, string> = {
  causes: '因果',
  before: '时序',
  hints: '暗示',
  setups: '铺设',
  callbacks: '回收',
  echoes: '呼应',
}

export const EDGE_TYPE_COLORS: Record<string, string> = {
  causes: '#dc2626',
  before: '#6b7280',
  hints: '#a78bfa',
  setups: '#7c3aed',
  callbacks: '#059669',
  echoes: '#0d9488',
}

export const VISIBILITY_LABELS: Record<CanonVisibility, string> = {
  public: '公开',
  private: '私有',
  partial: '部分',
}
