/**
 * 底图编辑状态机 + 局部 undo 栈。
 *
 * - mapEditMode：'images'（拼贴编辑）| 'draw'（手绘）| null（浏览）
 *   与 pickingMode / drawMode 互斥，由 WorldView 统一编排
 * - 局部 undo：编辑态内 Ctrl+Z/Y 走这里（画笔/删除高频，不刷掉全局 50 步）；
 *   退出编辑态即恢复全局栈。变换（拖/缩放）不进 undo——粒度是增删/层序
 * - queueLayerPatch：编辑期高频变换，本地立即生效 + 400ms 防抖合并落库
 * - importImage：上传 → 读自然尺寸 → 以视图中心放置（宽=视口 1/3，等比高）
 */
import { ref } from 'vue'
import { worldApi } from '../../../services/api'
import { getApiBase } from '../../../services/api/transport'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from './useWorld'
import type { MapLayerPatch, Point, WorldMapLayer } from '../engine/types'

export type MapEditMode = 'images' | 'draw' | null

const mapEditMode = ref<MapEditMode>(null)
const selectedLayerId = ref<string | null>(null)

// ===== 画笔工具状态 =====
const penColor = ref('#6b5537')
const penWidth = ref(4)
const eraserMode = ref(false)

// ===== 局部 undo 栈 =====
interface EditCommand {
  undo: () => Promise<void>
  redo: () => Promise<void>
}
const MAX = 80
const editPast: EditCommand[] = []
const editFuture: EditCommand[] = []
const canEditUndo = ref(false)
const canEditRedo = ref(false)

function syncEdit() {
  canEditUndo.value = editPast.length > 0
  canEditRedo.value = editFuture.length > 0
}
function pushEdit(cmd: EditCommand) {
  editPast.push(cmd)
  if (editPast.length > MAX) editPast.shift()
  editFuture.length = 0
  syncEdit()
}
export async function editUndo() {
  const c = editPast.pop()
  if (!c) return
  await c.undo()
  editFuture.push(c)
  syncEdit()
}
export async function editRedo() {
  const c = editFuture.pop()
  if (!c) return
  await c.redo()
  editPast.push(c)
  syncEdit()
}
function clearEditHistory() {
  editPast.length = 0
  editFuture.length = 0
  syncEdit()
}

// ===== 模式切换 =====
function enterMapEdit(mode: Exclude<MapEditMode, null>) {
  mapEditMode.value = mode
  selectedLayerId.value = null
  clearEditHistory()
}
function exitMapEdit() {
  // 冲刷未落库的变换防抖
  flushPatches()
  mapEditMode.value = null
  selectedLayerId.value = null
}

// ===== 图片变换：本地立即 + 防抖落库 =====
interface PendingPatch extends MapLayerPatch {
  _timer?: ReturnType<typeof setTimeout>
}
const pendingPatches = new Map<string, PendingPatch>()

function queueLayerPatch(bookId: string, layerId: string, patch: MapLayerPatch) {
  const { setMapLayers, mapLayers } = useWorld()
  // 本地立即生效（渲染层 watch 跟随）
  setMapLayers(mapLayers.value.map((l) => (l.id === layerId ? { ...l, ...patch } : l)))
  // 合并 + 防抖落库
  const prev = pendingPatches.get(layerId) || {}
  const merged: PendingPatch = { ...prev, ...patch }
  if (prev._timer) clearTimeout(prev._timer)
  merged._timer = setTimeout(async () => {
    const { _timer, ...rest } = merged
    void _timer
    pendingPatches.delete(layerId)
    try {
      await worldApi.updateMapLayer(bookId, layerId, rest)
    } catch {
      /* 落库失败静默（下次任何变换会再带出去；刷新丢失可接受） */
    }
  }, 400)
  pendingPatches.set(layerId, merged)
}

async function flushPatches() {
  for (const [layerId, p] of pendingPatches) {
    if (p._timer) clearTimeout(p._timer)
    const { _timer, ...rest } = p
    void _timer
    try {
      const bookId = useWorld().loadedBookId.value
      if (bookId) await worldApi.updateMapLayer(bookId, layerId, rest)
    } catch {
      /* 同上 */
    }
  }
  pendingPatches.clear()
}

// ===== 图片删除（局部 undo）=====
async function removeLayer(bookId: string, layerId: string) {
  const { mapLayers, setMapLayers } = useWorld()
  const snap = mapLayers.value.find((l) => l.id === layerId)
  if (!snap) return
  const before = [...mapLayers.value]
  const beforeIdx = before.findIndex((l) => l.id === layerId)
  setMapLayers(before.filter((l) => l.id !== layerId))
  await worldApi.deleteMapLayer(bookId, layerId)
  if (selectedLayerId.value === layerId) selectedLayerId.value = null
  pushEdit({
    undo: async () => {
      // 幂等重建（2026-09-04 审计修复）：带原 id——redo 删的是原 id，
      // 此前重建得新 id → redo 404、图层累积重复
      const r = await worldApi.createMapLayer(bookId, {
        id: layerId,
        image_url: snap.image_url,
        x: snap.x,
        y: snap.y,
        w: snap.w,
        h: snap.h,
      })
      const arr = [...useWorld().mapLayers.value]
      arr.splice(Math.min(beforeIdx, arr.length), 0, r)
      setMapLayers(arr)
      selectedLayerId.value = r.id
    },
    redo: async () => {
      await worldApi.deleteMapLayer(bookId, layerId)
      useWorld().setMapLayers(useWorld().mapLayers.value.filter((l) => l.id !== layerId))
      if (selectedLayerId.value === layerId) selectedLayerId.value = null
    },
  })
}

// ===== 层序：置顶/置底（全量重编 z_index）=====
async function reorderLayer(bookId: string, layerId: string, dir: 'front' | 'back') {
  const { mapLayers, setMapLayers } = useWorld()
  const before = [...mapLayers.value]
  const arr = [...mapLayers.value]
  const i = arr.findIndex((l) => l.id === layerId)
  if (i < 0) return
  const [item] = arr.splice(i, 1)
  if (dir === 'front') arr.push(item)
  else arr.unshift(item)
  setMapLayers(arr.map((l, idx) => ({ ...l, z_index: idx + 1 })))
  await Promise.all(arr.map((l, idx) => worldApi.updateMapLayer(bookId, l.id, { z_index: idx + 1 })))
  pushEdit({
    undo: async () => {
      setMapLayers(before)
      await Promise.all(before.map((l) => worldApi.updateMapLayer(bookId, l.id, { z_index: l.z_index })))
    },
    redo: async () => {
      setMapLayers(arr.map((l, idx) => ({ ...l, z_index: idx + 1 })))
      await Promise.all(arr.map((l, idx) => worldApi.updateMapLayer(bookId, l.id, { z_index: idx + 1 })))
    },
  })
}

// ===== 笔迹增删（局部 undo；redo 重建新 id——笔迹无跨引用，可接受）=====
async function addStroke(bookId: string, color: string, width: number, points: Point[]) {
  const s = await useWorld().createMapStroke(bookId, color, width, points)
  pushEdit({
    undo: async () => {
      await useWorld().deleteMapStrokeData(bookId, s.id)
    },
    redo: async () => {
      // 幂等重建（2026-09-04 审计修复）：带原 id——随后 undo 删原 id 不再 404
      await useWorld().createMapStroke(bookId, color, width, points, s.id)
    },
  })
  return s
}

async function eraseStroke(bookId: string, strokeId: string) {
  const { mapStrokes } = useWorld()
  const snap = mapStrokes.value.find((s) => s.id === strokeId)
  if (!snap) return
  await useWorld().deleteMapStrokeData(bookId, strokeId)
  pushEdit({
    undo: async () => {
      // 幂等重建（2026-09-04 审计修复）：带原 id——redo 删原 id 不再 404
      await useWorld().createMapStroke(bookId, snap.color, snap.width, snap.points, strokeId)
    },
    redo: async () => {
      await useWorld().deleteMapStrokeData(bookId, strokeId)
    },
  })
}

// ===== 导入图片 =====
async function importImage(
  bookId: string,
  file: File,
  centerX: number,
  centerY: number,
  viewW: number,
): Promise<WorldMapLayer> {
  const { url } = await worldApi.uploadMapImage(bookId, file)
  // 读自然尺寸（宽高比）
  const full = await resolveImageUrl(url)
  const ratio = await new Promise<number>((res) => {
    const img = new Image()
    img.onload = () => res(img.naturalWidth > 0 ? img.naturalHeight / img.naturalWidth : 1)
    img.onerror = () => res(1)
    img.src = full
  })
  const w = Math.max(60, viewW / 3)
  const h = w * ratio
  const layer = await useWorld().createMapLayer(bookId, {
    image_url: url,
    x: centerX,
    y: centerY,
    w,
    h,
  })
  selectedLayerId.value = layer.id
  return layer
}

// ===== 清空笔迹（局部 undo：退出编辑态前可撤）=====
async function clearAllStrokes(bookId: string) {
  const { mapStrokes, setMapStrokes } = useWorld()
  if (!mapStrokes.value.length) return
  const { show } = useConfirmDialog()
  const ok = await show({
    title: '清空笔迹',
    message: `确定清空全部 ${mapStrokes.value.length} 条笔迹吗？`,
    warning: '清空后可在编辑态内 Ctrl+Z 撤销（退出编辑后不可）。',
    confirmText: '清空',
  })
  if (!ok) return
  const snaps = [...mapStrokes.value]
  setMapStrokes([])
  await Promise.all(snaps.map((s) => worldApi.deleteMapStroke(bookId, s.id)))
  pushEdit({
    undo: async () => {
      for (const s of snaps) {
        await useWorld().createMapStroke(bookId, s.color, s.width, s.points)
      }
    },
    redo: async () => {
      useWorld().setMapStrokes([])
      await Promise.all(snaps.map((s) => worldApi.deleteMapStroke(bookId, s.id)))
    },
  })
}

// ===== 图片 URL 解析（dev 下直连后端 origin，同源相对路径）=====
let originCache: string | null = null
export async function resolveImageUrl(url: string): Promise<string> {
  if (/^https?:/.test(url)) return url
  if (!originCache) {
    const base = await getApiBase() // http://127.0.0.1:{port}/api 或 /api
    originCache = base.replace(/\/api\/?$/, '')
  }
  return originCache + url
}

export function useMapEdit() {
  return {
    mapEditMode,
    selectedLayerId,
    penColor,
    penWidth,
    eraserMode,
    canEditUndo,
    canEditRedo,
    enterMapEdit,
    exitMapEdit,
    queueLayerPatch,
    removeLayer,
    reorderLayer,
    addStroke,
    eraseStroke,
    clearAllStrokes,
    importImage,
  }
}
