/**
 * Canon（作者脑中世界图谱）API（V4.0 新建）。
 *
 * 设计依据：docs/generation-v4.0-canon.md §5
 *
 * 端点（前缀 /api/books/{book_id}/canon）：
 * - GET    /                  获取整书图谱（可视化主查询）
 * - GET    /nodes             列出节点
 * - POST   /nodes             创建节点
 * - PUT    /nodes/{id}        更新节点
 * - DELETE /nodes/{id}        删除节点
 * - GET    /edges             列出边
 * - POST   /edges             创建边
 * - PUT    /edges/{id}        更新边
 * - DELETE /edges/{id}        删除边
 * - GET    /nodes/{id}/neighbors   邻居查询
 * - GET    /hooks             悬空伏笔
 * - POST   /check             一致性检查
 * - POST   /impact/{id}       变更连锁分析
 * - POST   /extract           自动提取
 */

import { requestJson } from '../transport'

// ============================================================
// 类型定义
// ============================================================

export type CanonNodeType = 'character' | 'event' | 'object' | 'place' | 'hook'
export type CanonEdgeType = 'causes' | 'before' | 'hints' | 'setups' | 'callbacks' | 'echoes'
export type CanonVisibility = 'public' | 'private' | 'partial'

export interface CanonNode {
  id: string
  book_id: string
  type: CanonNodeType
  label: string
  canon_text: string
  public_text: string
  visibility: CanonVisibility
  appeared_in: number[]
  revealed_in: number[]
  reveal_plan: string
  expected_reveal_chapter: number | null
  tags: string[]
  confidence: string
  source: string
  metadata: Record<string, any>
  /** C2 信息面挂接：ref 指向世界对象（entity|location|ledger）；空=自由节点 */
  ref_type?: string | null
  ref_id?: string | null
  created_at: string
  updated_at: string
}

export interface CanonEdge {
  id: string
  book_id: string
  source_id: string
  target_id: string
  type: CanonEdgeType
  strength: number
  visibility: CanonVisibility
  note: string
  established_in: number[]
  metadata: Record<string, any>
  created_at: string
  updated_at: string
}

export interface CanonGraph {
  nodes: CanonNode[]
  edges: CanonEdge[]
}

export interface CanonNodeCreate {
  book_id: string
  type: CanonNodeType
  label: string
  canon_text?: string
  public_text?: string
  visibility?: CanonVisibility
  reveal_plan?: string
  expected_reveal_chapter?: number | null
  tags?: string[]
  metadata?: Record<string, any>
  ref_type?: string | null
  ref_id?: string | null
}

export interface CanonNodeUpdate {
  type?: CanonNodeType
  label?: string
  canon_text?: string
  public_text?: string
  visibility?: CanonVisibility
  reveal_plan?: string
  expected_reveal_chapter?: number | null
  tags?: string[]
  metadata?: Record<string, any>
  appeared_in?: number[]
  revealed_in?: number[]
  ref_type?: string | null
  ref_id?: string | null
}

export interface CanonEdgeCreate {
  book_id: string
  source_id: string
  target_id: string
  type: CanonEdgeType
  strength?: number
  visibility?: CanonVisibility
  note?: string
  established_in?: number[]
  metadata?: Record<string, any>
}

export interface CanonEdgeUpdate {
  type?: CanonEdgeType
  strength?: number
  visibility?: CanonVisibility
  note?: string
  established_in?: number[]
  metadata?: Record<string, any>
}

export interface ConsistencyIssue {
  severity: 'error' | 'warning' | 'info'
  kind: string
  node_id: string | null
  node_label: string | null
  detail: string
  evidence: string | null
  suggestions: string[]
}

export interface ConsistencyCheckResult {
  issues: ConsistencyIssue[]
  stats: {
    private_total: number
    private_leaked: number
    hooks_open: number
    hooks_orphan: number
    issues_total: number
    errors: number
    warnings: number
    infos: number
  }
}

export interface ImpactItem {
  node_id: string
  node_label: string
  node_type: string
  impact_type: 'contradiction' | 'tone_shift' | 'requires_setup' | 'ok'
  detail: string
  suggestions: string[]
}

export interface ImpactAnalysisResult {
  changed_node: CanonNode
  affected: ImpactItem[]
  total_affected: number
}

export interface NeighborsResult {
  center: CanonNode
  nodes: CanonNode[]
  edges: CanonEdge[]
}

export interface CanonExtractionResult {
  extracted_nodes: any[]
  extracted_edges: any[]
  committed: boolean
  message: string
}

// ============================================================
// API
// ============================================================

export const canonApi = {
  // 整书图谱
  getGraph: (bookId: string, filters?: { node_type?: CanonNodeType; visibility?: CanonVisibility }) => {
    const params = new URLSearchParams()
    if (filters?.node_type) params.set('node_type', filters.node_type)
    if (filters?.visibility) params.set('visibility', filters.visibility)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return requestJson<CanonGraph>(`/books/${bookId}/canon${qs}`)
  },

  // 节点 CRUD
  listNodes: (bookId: string, filters?: { node_type?: CanonNodeType; visibility?: CanonVisibility; tag?: string }) => {
    const params = new URLSearchParams()
    if (filters?.node_type) params.set('node_type', filters.node_type)
    if (filters?.visibility) params.set('visibility', filters.visibility)
    if (filters?.tag) params.set('tag', filters.tag)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return requestJson<CanonNode[]>(`/books/${bookId}/canon/nodes${qs}`)
  },

  createNode: (bookId: string, data: CanonNodeCreate) =>
    requestJson<CanonNode>(`/books/${bookId}/canon/nodes`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateNode: (bookId: string, nodeId: string, data: CanonNodeUpdate) =>
    requestJson<CanonNode>(`/books/${bookId}/canon/nodes/${nodeId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteNode: (bookId: string, nodeId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/canon/nodes/${nodeId}`, {
      method: 'DELETE',
    }),

  // 边 CRUD
  listEdges: (bookId: string, edgeType?: CanonEdgeType) => {
    const qs = edgeType ? `?edge_type=${edgeType}` : ''
    return requestJson<CanonEdge[]>(`/books/${bookId}/canon/edges${qs}`)
  },

  createEdge: (bookId: string, data: CanonEdgeCreate) =>
    requestJson<CanonEdge>(`/books/${bookId}/canon/edges`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateEdge: (bookId: string, edgeId: string, data: CanonEdgeUpdate) =>
    requestJson<CanonEdge>(`/books/${bookId}/canon/edges/${edgeId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteEdge: (bookId: string, edgeId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/canon/edges/${edgeId}`, {
      method: 'DELETE',
    }),

  // 图查询
  getNeighbors: (bookId: string, nodeId: string, depth: number = 2) =>
    requestJson<NeighborsResult>(`/books/${bookId}/canon/nodes/${nodeId}/neighbors?depth=${depth}`),

  listHooks: (bookId: string, onlyOpen: boolean = true) =>
    requestJson<CanonNode[]>(`/books/${bookId}/canon/hooks?only_open=${onlyOpen}`),

  // 一致性检查
  checkConsistency: (bookId: string, text: string) =>
    requestJson<ConsistencyCheckResult>(`/books/${bookId}/canon/check`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  // 变更连锁分析
  analyzeImpact: (bookId: string, nodeId: string, proposedChange?: Record<string, any>) =>
    requestJson<ImpactAnalysisResult>(`/books/${bookId}/canon/impact/${nodeId}`, {
      method: 'POST',
      body: JSON.stringify({ proposed_change: proposedChange || null, max_depth: 2 }),
    }),

  // 自动提取
  extract: (bookId: string, chapterId: string, autoCommit: boolean = false) =>
    requestJson<CanonExtractionResult>(`/books/${bookId}/canon/extract`, {
      method: 'POST',
      body: JSON.stringify({ chapter_id: chapterId, auto_commit: autoCommit }),
    }),
}
