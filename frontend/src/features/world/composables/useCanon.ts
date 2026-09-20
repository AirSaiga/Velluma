/**
 * Canon（真相层）状态管理（C1 自 features/canon 迁入 world，随 CanonView 退役）。
 *
 * 职责：
 * - 加载/缓存整书图谱（模块级单例：真相账本 / 真相详情共享同一份状态）
 * - 节点/边 CRUD（自动刷新缓存，落库后广播 velluma:world-refresh）
 *   ⚠ 边 CRUD 与 analyzeImpact 现无 UI 消费（2026-09-03 因果图谱模态退役——建边
 *   零入口致边恒为零；后端边表/路由保留，此处契约同步保留，勿删）
 *
 * 设计依据：docs/reports/canon-world-fusion.md（C1：UI 承载融合，后端零改动）
 * 术语表里化（docs/design/canon-fusion）：canon_text→里 / public_text→表 /
 * private→秘密 / partial→半露。
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
import { WORLD_REFRESH_EVENT } from './useWorldSlice'

export interface UseCanon {
  nodes: Ref<CanonNode[]>
  edges: Ref<CanonEdge[]>
  loading: Ref<boolean>
  error: Ref<string | null>
  // 控制
  load: (bookId: string) => Promise<void>
  /** 幂等加载：当前书已载过则跳过（WorldView 挂载与抽屉首开不重复请求） */
  ensureLoaded: (bookId: string) => Promise<void>
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

const nodes = ref<CanonNode[]>([])
const edges = ref<CanonEdge[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

let currentBookId: string | null = null

/** 副作用：canon 数据落库后广播世界刷新（与伏笔/期待/世界观同契约） */
function broadcastRefresh() {
  window.dispatchEvent(new CustomEvent(WORLD_REFRESH_EVENT))
}

export function useCanon(): UseCanon {

  async function load(bookId: string) {
    currentBookId = bookId
    await refresh()
  }

  async function ensureLoaded(bookId: string) {
    if (currentBookId === bookId && nodes.value.length) return
    await load(bookId)
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
    broadcastRefresh()
    return node
  }

  async function updateNode(bookId: string, nodeId: string, data: CanonNodeUpdate): Promise<CanonNode> {
    const node = await canonApi.updateNode(bookId, nodeId, data)
    await refresh()
    broadcastRefresh()
    return node
  }

  async function deleteNode(bookId: string, nodeId: string): Promise<void> {
    await canonApi.deleteNode(bookId, nodeId)
    await refresh()
    broadcastRefresh()
  }

  async function createEdge(bookId: string, data: CanonEdgeCreate): Promise<CanonEdge> {
    const edge = await canonApi.createEdge(bookId, data)
    await refresh()
    broadcastRefresh()
    return edge
  }

  async function updateEdge(bookId: string, edgeId: string, data: CanonEdgeUpdate): Promise<CanonEdge> {
    const edge = await canonApi.updateEdge(bookId, edgeId, data)
    await refresh()
    broadcastRefresh()
    return edge
  }

  async function deleteEdge(bookId: string, edgeId: string): Promise<void> {
    await canonApi.deleteEdge(bookId, edgeId)
    await refresh()
    broadcastRefresh()
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
    ensureLoaded,
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
// 常量（UI 显示用，术语随 C1 表里化）
// ============================================================

export const NODE_TYPE_LABELS: Record<CanonNodeType, string> = {
  character: '角色',
  event: '叙事',
  object: '物件',
  place: '地点',
  // C1 过渡期称「钩子」避免与世界页伏笔账本撞名；C2 该类型并入伏笔账本后退役
  hook: '钩子',
}

export const NODE_TYPE_COLORS: Record<CanonNodeType, string> = {
  character: '#4f46e5', // 靛蓝
  event: '#0891b2',     // 青蓝
  object: '#ca8a04',    // 土黄
  place: '#16a34a',     // 绿
  hook: '#7c3aed',      // 紫（对齐伏笔账本语义色）
}

export const EDGE_TYPE_LABELS: Record<string, string> = {
  causes: '因果',
  before: '先后',
  hints: '暗示',
  setups: '铺垫',
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

/** 表里三态的用户语言（拍板 2026-08-17：三态直切，不用推导制） */
export const VISIBILITY_LABELS: Record<CanonVisibility, string> = {
  public: '公开',
  private: '秘密',
  partial: '半露',
}

/** 秘密/半露的朱砂语义色（docs/design/canon-fusion 朱点贯穿令牌）。
 *  值=--cinnabar 浅档（地图画布恒亮，JS 恒取浅档自洽；深档差异由 CSS 消费侧承担）。 */
export const ZHU_COLOR = '#a63e2a'
