<script setup lang="ts">
/**
 * 世界地图（Leaflet CRS.Simple + 零图片点阵画布）。
 *
 * 图层（自下而上）：底图占位 → move 轨迹线 → 疆域 polygon → 事件 marker → 地点 marker → 人物 marker。
 * 地点/人物/事件用 divIcon 自定义视觉（wm- 前缀样式在底部非 scoped style 块——
 * Leaflet 创建的 DOM 不在 Vue scoped 作用域内）。
 *
 * 坐标约定：Leaflet [lat,lng]，CRS.Simple 下 lat=y、lng=x；内部坐标 Point=[x,y]。
 * 设计意图：事件溯源的世界地图——拖时间轴，人物/疆域/轨迹/历史事件随 currentTime 回放。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from '../composables/useWorld'
import { useMapEdit, resolveImageUrl, editUndo, editRedo } from '../composables/useMapEdit'
import { eventPoint, stripPointFromNote } from '../engine/eventPoint'
import { EVENT_TYPE_COLOR, getTemplate } from '../engine/eventTemplates'
import { formatTime } from '../engine/timeFormat'
import type { DrawMode, WorldLocation, WorldMapLayer } from '../engine/types'

const props = defineProps<{
  bookId: string
  /** 拾取模式：null=浏览, 'location'=点选建地点（点击 emit pick） */
  pickingMode?: 'location' | null
  /** 绘制模式：非 null 时地图点击收集顶点，双击/Enter/完成闭合后 emit draw-complete */
  drawMode?: DrawMode
}>()

const emit = defineEmits<{
  pick: [point: [number, number]]
  'draw-complete': [points: [number, number][]]
  'entity-click': [entityId: string]
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let baseImageLayer: L.LayerGroup | null = null
let trackLayer: L.LayerGroup | null = null
let territoryLayer: L.LayerGroup | null = null
let eventLayer: L.LayerGroup | null = null
let markerLayer: L.LayerGroup | null = null
let characterLayer: L.LayerGroup | null = null
let rippleLayer: L.LayerGroup | null = null
let drawLayer: L.LayerGroup | null = null
let editHitLayer: L.LayerGroup | null = null
let editSelLayer: L.LayerGroup | null = null
/** 图片层 id → overlay 实例（编辑拖拽时直接 setBounds，避免整层重建闪烁） */
const overlayMap = new Map<string, L.ImageOverlay>()
/** 占位面板 marker（无底图时显示，有图自动隐藏） */
let placeholderMarker: L.Marker | null = null

// ---- 绘制草稿状态 ----
/** 草稿顶点（内部坐标 [x,y] + 时间戳；时间戳用于双击闭合时识别伴随产生的合成顶点） */
const draftPoints = ref<{ p: [number, number]; t: number }[]>([])
/** 橡皮筋连线（最后顶点 → 光标），mousemove 高频更新独立维护 */
let rubberLine: L.Polyline | null = null
const drawing = computed(() => !!props.drawMode)
/** 预览色与最终落图色一致：疆域紫 / 路径蓝（画出来的就是将要得到的） */
const drawColor = computed(() => (props.drawMode === 'territory' ? '#a855f7' : '#3b82f6'))

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const { locations, events, worldState, entities, currentTime, locationsById, updateLocationCoords, renameLocation, deleteLocation, mapLayers, mapStrokes } =
  useWorld()

const { mapEditMode, selectedLayerId, queueLayerPatch, removeLayer, reorderLayer, importImage, enterMapEdit, exitMapEdit, penColor, penWidth, eraserMode, canEditUndo, canEditRedo, addStroke, eraseStroke, clearAllStrokes } =
  useMapEdit()

const editingImages = computed(() => mapEditMode.value === 'images')
/** 任何沉浸编辑（疆域绘制 / 底图编辑）时数据层禁交互 */
const inEditMode = computed(() => !!props.drawMode || mapEditMode.value !== null)
const selectedLayer = computed(
  () => mapLayers.value.find((l) => l.id === selectedLayerId.value) || null,
)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 图层显隐（右上工具条）
const layerVisible = ref({
  tracks: true,
  territory: true,
  events: true,
  locations: true,
  characters: true,
})

const LAYER_TOGGLES: { key: keyof typeof layerVisible.value; icon: string; label: string }[] = [
  { key: 'characters', icon: 'users', label: '人物' },
  { key: 'locations', icon: 'map-pin', label: '地点' },
  { key: 'events', icon: 'flag', label: '事件' },
  { key: 'territory', icon: 'globe', label: '疆域' },
  { key: 'tracks', icon: 'arrows-right-left', label: '移动轨迹' },
]

const entitiesById = computed<
  Record<string, { name: string; entity_type: string; intro: string; importance?: number }>
>(() => {
  const m: Record<string, { name: string; entity_type: string; intro: string; importance?: number }> = {}
  for (const e of entities.value)
    m[e.id] = { name: e.name, entity_type: e.entity_type, intro: e.intro || '', importance: e.importance }
  return m
})

/** zoom 低于此值隐藏地点/人物名字标签（只留色点），避免密集重叠 */
const LABEL_ZOOM = 0
const showLabels = () => (map ? map.getZoom() >= LABEL_ZOOM : true)

// 内部坐标范围 0..1000
const BOUNDS = L.latLngBounds([[0, 0], [1000, 1000]])

// 地点三类配色（空心环点，与实心人物点区分）
const LOC_KIND_COLOR: Record<string, string> = {
  point: '#7c6aad',
  region: '#10b981',
  route: '#60a5fa',
}

function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string,
  )
}

// ===== 底图：图片拼贴层（常驻最底）+ images 编辑态交互 =====

function layerBounds(l: { x: number; y: number; w: number; h: number }): L.LatLngBounds {
  return L.latLngBounds([
    [l.y - l.h / 2, l.x - l.w / 2],
    [l.y + l.h / 2, l.x + l.w / 2],
  ])
}

async function renderBaseImages() {
  if (!map || !baseImageLayer) return
  baseImageLayer.clearLayers()
  overlayMap.clear()
  for (const l of mapLayers.value) {
    const url = await resolveImageUrl(l.image_url)
    if (!map || !baseImageLayer) return // 卸载竞态
    const ov = L.imageOverlay(url, layerBounds(l), {
      opacity: l.opacity ?? 1,
      interactive: false,
    })
    overlayMap.set(l.id, ov)
    baseImageLayer.addLayer(ov)
  }
  renderPlaceholder()
}

/** 占位面板：无底图（图片+笔迹皆空）时显示 */
function renderPlaceholder() {
  if (!map) return
  const empty = mapLayers.value.length === 0 && mapStrokes.value.length === 0
  if (empty && !placeholderMarker) {
    placeholderMarker = L.marker([500, 500], {
      icon: makePlaceholderIcon(),
      interactive: false,
      zIndexOffset: -1000,
    }).addTo(map)
  } else if (!empty && placeholderMarker) {
    map.removeLayer(placeholderMarker)
    placeholderMarker = null
  }
}

/** images 编辑态：每图透明点击区（选中）+ 选中框/手柄 */
function renderEditImages() {
  if (!map || !editHitLayer || !editSelLayer) return
  editHitLayer.clearLayers()
  editSelLayer.clearLayers()
  geomRefs.clear()
  if (mapEditMode.value !== 'images') return
  for (const l of mapLayers.value) {
    const hit = L.rectangle(layerBounds(l), {
      stroke: false,
      fill: true,
      fillColor: '#7c6aad',
      fillOpacity: 0.05,
    })
    hit.on('click', (e) => {
      L.DomEvent.stopPropagation((e as unknown) as Event)
      selectedLayerId.value = l.id
    })
    editHitLayer.addLayer(hit)
  }
  renderSelection()
}

/** 选中图层的编辑框几何引用（拖动中直接 setBounds/setLatLng，不重建） */
const geomRefs = new Map<string, { rect: L.Rectangle; handles: L.Marker[] }>()

function makeCenterHandleIcon(): L.DivIcon {
  return L.divIcon({
    className: 'wm-handle-icon',
    html: '<div class="wm-handle wm-handle--center" title="拖动移动"></div>',
    iconSize: [0, 0],
  })
}
function makeCornerIcon(): L.DivIcon {
  return L.divIcon({
    className: 'wm-handle-icon',
    html: '<div class="wm-handle" title="拖动缩放"></div>',
    iconSize: [0, 0],
  })
}

function renderSelection() {
  if (!editSelLayer || !editHitLayer) return
  editSelLayer.clearLayers()
  geomRefs.clear()
  const l = selectedLayer.value
  if (!l || mapEditMode.value !== 'images') return
  const rect = L.rectangle(layerBounds(l), {
    color: '#7c6aad',
    weight: 1.5,
    dashArray: '6 4',
    fill: false,
    interactive: false,
  })
  editSelLayer.addLayer(rect)
  const handles: L.Marker[] = []

  // 中心手柄：拖动整图
  const center = L.marker([l.y, l.x], {
    icon: makeCenterHandleIcon(),
    draggable: true,
    zIndexOffset: 1000,
  })
  let last = { x: l.x, y: l.y, w: l.w, h: l.h }
  center.on('drag', (e) => {
    const ll = (e.target as L.Marker).getLatLng()
    last = { ...last, x: ll.lng, y: ll.lat }
    applyGeom(l.id, last)
  })
  center.on('dragend', () => {
    queueLayerPatch(props.bookId, l.id, { x: last.x, y: last.y })
    renderEditImages()
  })
  editSelLayer.addLayer(center)
  handles.push(center)

  // 4 角手柄：对角锚定自由缩放（w/h 独立，素材可拉伸）
  const anchors: [number, number][] = [
    [l.x + l.w / 2, l.y + l.h / 2], // 左上 → 锚右下
    [l.x - l.w / 2, l.y + l.h / 2], // 右上 → 锚左下
    [l.x - l.w / 2, l.y - l.h / 2], // 右下 → 锚左上
    [l.x + l.w / 2, l.y - l.h / 2], // 左下 → 锚右上
  ]
  const corners: [number, number][] = [
    [l.x - l.w / 2, l.y - l.h / 2],
    [l.x + l.w / 2, l.y - l.h / 2],
    [l.x + l.w / 2, l.y + l.h / 2],
    [l.x - l.w / 2, l.y + l.h / 2],
  ]
  corners.forEach(([cx, cy], i) => {
    const h = L.marker([cy, cx], {
      icon: makeCornerIcon(),
      draggable: true,
      zIndexOffset: 1000,
    })
    const [ax, ay] = anchors[i]
    h.on('drag', (e) => {
      const ll = (e.target as L.Marker).getLatLng()
      const nw = Math.max(20, Math.abs(ll.lng - ax))
      const nh = Math.max(20, Math.abs(ll.lat - ay))
      last = { x: (ax + ll.lng) / 2, y: (ay + ll.lat) / 2, w: nw, h: nh }
      applyGeom(l.id, last)
    })
    h.on('dragend', () => {
      queueLayerPatch(props.bookId, l.id, {
        x: last.x,
        y: last.y,
        w: last.w,
        h: last.h,
      })
      renderEditImages()
    })
    editSelLayer.addLayer(h)
    handles.push(h)
  })

  geomRefs.set(l.id, { rect, handles })
}

/** 拖动中本地几何跟随（overlay + 框 + 手柄）；数据与落库在 dragend */
function applyGeom(
  layerId: string,
  g: { x: number; y: number; w: number; h: number },
) {
  const b = layerBounds(g)
  overlayMap.get(layerId)?.setBounds(b)
  const refs = geomRefs.get(layerId)
  if (!refs) return
  refs.rect.setBounds(b)
  refs.handles[0]?.setLatLng([g.y, g.x])
  const cs: [number, number][] = [
    [g.x - g.w / 2, g.y - g.h / 2],
    [g.x + g.w / 2, g.y - g.h / 2],
    [g.x + g.w / 2, g.y + g.h / 2],
    [g.x - g.w / 2, g.y + g.h / 2],
  ]
  cs.forEach(([cx, cy], i) => refs.handles[i + 1]?.setLatLng([cy, cx]))
}

/** 以当前视图中心放置导入的图片（file 按钮与拖拽 drop 共用） */
async function importImageAtView(file: File) {
  if (!map) return
  const c = map.getCenter()
  const b = map.getBounds()
  const viewW = Math.abs(b.getEast() - b.getWest()) || 600
  await importImage(props.bookId, file, c.lng, c.lat, viewW)
}

async function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  try {
    await importImageAtView(f)
    showToast('图片已导入——拖中心移动，拖角缩放', 'success')
  } catch (err) {
    showToast('导入失败：' + ((err as Error)?.message || '未知错误'), 'error')
  } finally {
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function removeSelected() {
  if (selectedLayer.value) removeLayer(props.bookId, selectedLayer.value.id)
}

function toggleEdit(mode: 'images' | 'draw') {
  if (mapEditMode.value === mode) exitMapEdit()
  else enterMapEdit(mode)
}

// ===== 底图：手绘笔迹（canvas 覆盖层，rAF 全量重绘同步地图）=====

const PEN_COLORS = ['#6b5537', '#3f6212', '#1d4ed8', '#475569', '#b91c1c', '#1c1917']
const PEN_SIZES = [2, 4, 8]

const strokeCanvasRef = ref<HTMLCanvasElement | null>(null)
/** 正在画的笔（内部坐标，实时预览；pointerup 时落库） */
const draftStroke = ref<[number, number][]>([])
const drawingMap = computed(() => mapEditMode.value === 'draw')
let painting = false
let strokeRafId: number | null = null

function scheduleStrokeRedraw() {
  if (strokeRafId !== null) return
  strokeRafId = requestAnimationFrame(() => {
    strokeRafId = null
    drawStrokes()
  })
}

function drawStrokes() {
  const cv = strokeCanvasRef.value
  if (!cv || !map) return
  const dpr = window.devicePixelRatio || 1
  const w = cv.clientWidth
  const h = cv.clientHeight
  if (w === 0 || h === 0) return
  const pw = Math.round(w * dpr)
  const ph = Math.round(h * dpr)
  if (cv.width !== pw || cv.height !== ph) {
    cv.width = pw
    cv.height = ph
  }
  const ctx = cv.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  // 已存笔迹 + 正在画的草稿笔
  const all: { color: string; width: number; points: [number, number][] }[] = [
    ...mapStrokes.value.map((s) => ({ color: s.color, width: s.width, points: s.points as [number, number][] })),
  ]
  if (draftStroke.value.length > 1) {
    all.push({ color: penColor.value, width: penWidth.value, points: draftStroke.value })
  }
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const s of all) {
    if (s.points.length < 2) continue
    const pts = s.points.map(([x, y]) => {
      const cp = map!.latLngToContainerPoint([y, x])
      return [cp.x, cp.y] as [number, number]
    })
    ctx.strokeStyle = s.color
    ctx.lineWidth = s.width
    ctx.beginPath()
    ctx.moveTo(pts[0][0], pts[0][1])
    // 中点二次贝塞尔平滑
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i][0] + pts[i + 1][0]) / 2
      const my = (pts[i][1] + pts[i + 1][1]) / 2
      ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my)
    }
    ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1])
    ctx.stroke()
  }
}

function canvasToInternal(e: PointerEvent): [number, number] | null {
  const cv = strokeCanvasRef.value
  if (!cv || !map) return null
  const r = cv.getBoundingClientRect()
  const cp = L.point(e.clientX - r.left, e.clientY - r.top)
  const ll = map.containerPointToLatLng(cp)
  return [ll.lng, ll.lat]
}

function onStrokeDown(e: PointerEvent) {
  if (mapEditMode.value !== 'draw') return
  const p = canvasToInternal(e)
  if (!p) return
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
  painting = true
  if (eraserMode.value) {
    eraseAtPoint(p)
  } else {
    draftStroke.value = [p]
    scheduleStrokeRedraw()
  }
}
function onStrokeMove(e: PointerEvent) {
  if (!painting || mapEditMode.value !== 'draw') return
  const p = canvasToInternal(e)
  if (!p || !map) return
  if (eraserMode.value) {
    eraseAtPoint(p)
    return
  }
  const last = draftStroke.value[draftStroke.value.length - 1]
  if (!last) return
  // 屏幕空间 >1.5px 才收点（降密度）
  const a = map.latLngToContainerPoint([last[1], last[0]])
  const b = map.latLngToContainerPoint([p[1], p[0]])
  if (a.distanceTo(b) > 1.5) {
    draftStroke.value = [...draftStroke.value, p]
    scheduleStrokeRedraw()
  }
}
async function onStrokeUp() {
  if (!painting) return
  painting = false
  const pts = draftStroke.value
  draftStroke.value = []
  scheduleStrokeRedraw()
  if (pts.length >= 2) {
    try {
      await addStroke(props.bookId, penColor.value, penWidth.value, pts)
    } catch (err) {
      showToast('笔迹保存失败：' + ((err as Error)?.message || ''), 'error')
    }
  }
}

/** 橡皮：屏幕空间点到各笔折线距离 < 阈值 → 删除命中的那笔 */
function eraseAtPoint(p: [number, number]) {
  if (!map) return
  const cp = map.latLngToContainerPoint([p[1], p[0]])
  for (const s of [...mapStrokes.value].reverse()) {
    let hit = false
    const pts = s.points as [number, number][]
    for (let i = 0; i < pts.length - 1 && !hit; i++) {
      const a = map.latLngToContainerPoint([pts[i][1], pts[i][0]])
      const b = map.latLngToContainerPoint([pts[i + 1][1], pts[i + 1][0]])
      if (distToSeg(cp, a, b) < 10 + s.width / 2) hit = true
    }
    if (hit) {
      eraseStroke(props.bookId, s.id)
      return
    }
  }
}
function distToSeg(p: L.Point, a: L.Point, b: L.Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return p.distanceTo(a)
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return p.distanceTo(L.point(a.x + t * dx, a.y + t * dy))
}

function renderMarkers() {
  if (!map || !markerLayer) return
  markerLayer.clearLayers()
  if (!layerVisible.value.locations) return
  const withLabel = showLabels()
  for (const loc of locations.value) {
    if (loc.coord_x == null || loc.coord_y == null) continue
    const color = LOC_KIND_COLOR[loc.kind] || LOC_KIND_COLOR.point
    const icon = L.divIcon({
      className: 'wm-loc-icon',
      html: `<div class="wm-loc" style="--c:${color}"><span class="wm-loc-ring"></span>${
        withLabel ? `<span class="wm-loc-name">${esc(loc.name)}</span>` : ''
      }</div>`,
      iconSize: [0, 0],
    })
    // draggable：拖拽微调位置（松手落库，不进 undo）；绘制期禁用交互让点击穿透到地图
    const m = L.marker([loc.coord_y, loc.coord_x], {
      icon,
      title: loc.name,
      draggable: !inEditMode.value,
      interactive: !inEditMode.value,
    })
    m.on('dragend', () => {
      const ll = m.getLatLng()
      updateLocationCoords(props.bookId, loc.id, ll.lng, ll.lat)
    })
    m.bindPopup(buildLocPopupHtml(loc))
    markerLayer.addLayer(m)
  }
}

/** 地点 popup：名字 + 类型/简介 + 就地改名/删除（事件在 popupopen 委托绑定） */
function buildLocPopupHtml(loc: WorldLocation): string {
  return (
    `<div class="wm-pop-title">${esc(loc.name)}</div>` +
    `<span class="wm-pop-sub">${esc(loc.kind)}</span>` +
    (loc.intro ? `<div class="wm-pop-intro">${esc(loc.intro)}</div>` : '') +
    `<div class="wm-pop-edit" data-loc-id="${loc.id}">` +
    `<input class="wm-pop-input" data-loc-name value="${esc(loc.name)}" />` +
    `<button class="wm-pop-btn" data-act="save" title="保存改名">改名</button>` +
    `<button class="wm-pop-btn wm-pop-btn--danger" data-act="del" title="删除地点">删除</button>` +
    `</div>`
  )
}

/** move 轨迹线：完成的=点画墨线；在途=青墨虚线流动（行军中） */
function renderTracks() {
  if (!map || !trackLayer) return
  trackLayer.clearLayers()
  if (!layerVisible.value.tracks) return
  const t = currentTime.value
  for (const e of events.value) {
    if (e.event_type !== 'move') continue
    if (e.time_start > t) continue // 还没发生
    const path = (e.payload.path as [number, number][] | undefined) || []
    if (path.length < 2) continue
    const latlngs = path.map(([x, y]) => [y, x] as [number, number])
    const inTransit = t < e.time_end
    const line = L.polyline(
      latlngs,
      inTransit
        ? {
            color: '#3f6f8f',
            weight: 2.6,
            opacity: 0.9,
            dashArray: '9 7',
            lineCap: 'round',
            className: 'wm-track-flow',
            interactive: !inEditMode.value,
          }
        : {
            color: '#6b5a44',
            weight: 2.2,
            opacity: 0.5,
            dashArray: '1 6',
            lineCap: 'round',
            className: 'wm-track-ink',
            interactive: !inEditMode.value,
          },
    )
    trackLayer.addLayer(line)
  }
}

function renderCharacterMarkers() {
  if (!map || !characterLayer) return
  characterLayer.clearLayers()
  if (!layerVisible.value.characters) return
  // worldState.character_states：当前时刻谁在哪（事件溯源推演结果）
  for (const cs of worldState.value.character_states) {
    if (!cs.position || !cs.alive) continue
    const [x, y] = cs.position
    const ent = entitiesById.value[cs.entity_id]
    const label = ent?.name || cs.entity_id
    const color = ent?.entity_type === 'faction' ? '#a855f7' : '#f59e0b'
    const moving = cs.label.includes('在途')
    const star = (ent?.importance ?? 1) >= 7 // 核心角色星芒
    const withLabel = showLabels()
    const icon = L.divIcon({
      className: 'wm-char-icon',
      html: `<div class="wm-char${moving ? ' wm-char--moving' : ''}${star ? ' wm-char--star' : ''}" style="--c:${color}"><span class="wm-char-head"></span>${
        withLabel ? `<span class="wm-char-name">${esc(label)}</span>` : ''
      }</div>`,
      iconSize: [0, 0],
    })
    const m = L.marker([y, x], { icon, zIndexOffset: 500, interactive: !inEditMode.value })
    // 点击人物 → 打开实体抽屉（M2 详情/档案/编年史的家；替代旧 popup 信息层）
    m.on('click', () => {
      if (!inEditMode.value) emit('entity-click', cs.entity_id)
    })
    characterLayer.addLayer(m)
  }
}

function renderTerritory() {
  if (!map || !territoryLayer) return
  // 时刻大跳（点章节锚/事件点）→ 疆域平滑形变；连续小步（播放/拖游标）→ 即时贴合
  const jump = Math.abs(currentTime.value - lastStateTime) > 45
  lastStateTime = currentTime.value
  if (!layerVisible.value.territory) {
    territoryLayer.clearLayers()
    territoryPolys.clear()
    return
  }
  const desired = new Map(
    worldState.value.territory_states.map((ts) => [ts.faction_id, (ts.polygon || []) as [number, number][]]),
  )
  // 消失的疆域移除
  for (const [fid, entry] of [...territoryPolys]) {
    if (!desired.has(fid)) {
      territoryLayer.removeLayer(entry.poly)
      territoryPolys.delete(fid)
    }
  }
  for (const [fid, polygon] of desired) {
    if (!polygon || polygon.length < 3) continue
    const existing = territoryPolys.get(fid)
    if (!existing) {
      const poly = L.polygon(
        polygon.map(([x, y]) => [y, x] as [number, number]),
        TERRITORY_STYLE(),
      )
      const ent = entitiesById.value[fid]
      poly.bindPopup(`<b>${esc(ent?.name || fid)}</b><br/><span class="wm-pop-sub">疆域</span>`)
      territoryLayer.addLayer(poly)
      territoryPolys.set(fid, { poly, pts: polygon })
    } else if (jump) {
      morphPolygon(existing, polygon)
    } else {
      existing.pts = polygon
      existing.poly.setLatLngs(polygon.map(([x, y]) => [y, x] as [number, number]))
    }
  }
}

/** 疆域样式：墨迹晕染（古卷水彩——SVG 位移滤镜给边界毛边，见模板 wm-ink defs） */
function TERRITORY_STYLE(): L.PolylineOptions {
  return {
    color: '#6d5a86',
    weight: 2,
    opacity: 0.8,
    dashArray: '10 7',
    lineJoin: 'round' as const,
    fillColor: '#8b6f9e',
    fillOpacity: 0.13,
    interactive: !inEditMode.value,
    className: 'wm-territory',
  }
}

// ===== 疆域 morph（顶点数不同时按弧长重采样到相同 N 再插值）=====

interface TerritoryEntry {
  poly: L.Polygon
  pts: [number, number][]
  raf?: number
}
const territoryPolys = new Map<string, TerritoryEntry>()
let lastStateTime = 0

function resampleRing(pts: [number, number][], n: number): [number, number][] {
  if (pts.length === 0) return []
  if (pts.length === 1) return Array.from({ length: n }, () => [...pts[0]] as [number, number])
  const segs: number[] = []
  let total = 0
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length] // 闭合环采样
    const len = Math.hypot(b[0] - a[0], b[1] - a[1])
    segs.push(len)
    total += len
  }
  const out: [number, number][] = []
  for (let k = 0; k < n && total > 0; k++) {
    let target = (k / n) * total
    for (let i = 0; i < segs.length; i++) {
      if (target <= segs[i] || i === segs.length - 1) {
        const t = segs[i] === 0 ? 0 : Math.min(1, target / segs[i])
        const a = pts[i]
        const b = pts[(i + 1) % pts.length]
        out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
        break
      }
      target -= segs[i]
    }
  }
  return out
}

function morphPolygon(entry: TerritoryEntry, targetPts: [number, number][]) {
  const n = Math.max(16, Math.max(entry.pts.length, targetPts.length))
  const from = resampleRing(entry.pts, n)
  const to = resampleRing(targetPts, n)
  if (from.length !== n || to.length !== n) {
    entry.pts = targetPts
    entry.poly.setLatLngs(targetPts.map(([x, y]) => [y, x] as [number, number]))
    return
  }
  if (entry.raf) cancelAnimationFrame(entry.raf)
  const t0 = performance.now()
  const dur = 380
  const step = (now: number) => {
    const p = Math.min(1, (now - t0) / dur)
    const e = 1 - Math.pow(1 - p, 3) // easeOutCubic
    const cur = from.map(
      (f, i) =>
        [f[0] + (to[i][0] - f[0]) * e, f[1] + (to[i][1] - f[1]) * e] as [number, number],
    )
    entry.poly.setLatLngs(cur.map(([x, y]) => [y, x] as [number, number]))
    if (p < 1) entry.raf = requestAnimationFrame(step)
    else {
      entry.raf = undefined
      entry.pts = targetPts
    }
  }
  entry.raf = requestAnimationFrame(step)
}

// ===== 事件涟漪：游标前扫过的事件在其地点绽放类型色涟漪（静止时无动画）=====

let ripplePrevT: number | null = null

function spawnRipples(t: number) {
  if (!map || !rippleLayer) return
  if (ripplePrevT == null || t < ripplePrevT) {
    ripplePrevT = t // 回拖不重放涟漪
    return
  }
  const crossed = events.value.filter((e) => e.time_start > ripplePrevT! && e.time_start <= t)
  ripplePrevT = t
  for (const e of crossed) {
    const pt = eventPoint(e, locationsById.value)
    if (!pt) continue
    const color = EVENT_TYPE_COLOR[e.event_type] || '#94a3b8'
    const big =
      e.event_type === 'battle' || e.event_type === 'territory_change' || e.event_type === 'war_declare'
    const icon = L.divIcon({
      className: 'wm-ripple-icon',
      html: `<span class="wm-ripple${big ? ' wm-ripple--big' : ''}" style="--c:${color}"></span>`,
      iconSize: [0, 0],
    })
    const m = L.marker([pt[1], pt[0]], { icon, interactive: false, zIndexOffset: 900 })
    rippleLayer.addLayer(m)
    setTimeout(() => rippleLayer?.removeLayer(m), 1500)
  }
}

/**
 * 事件标记层（本页核心红利）：time_start ≤ 当前时刻、可定位的历史事件
 * 以类型色小菱形标注在地图上——拖时间轴，历史逐帧浮现。
 */
function renderEventMarkers() {
  if (!map || !eventLayer) return
  eventLayer.clearLayers()
  if (!layerVisible.value.events) return
  const t = currentTime.value
  for (const e of events.value) {
    if (e.time_start > t) continue
    const pt = eventPoint(e, locationsById.value)
    if (!pt) continue
    const color = EVENT_TYPE_COLOR[e.event_type] || '#94a3b8'
    const label = getTemplate(e.event_type)?.label || e.event_type
    const icon = L.divIcon({
      className: 'wm-evt-icon',
      html: `<span class="wm-evt" style="--c:${color}" title="${esc(label)}"></span>`,
      iconSize: [0, 0],
    })
    const m = L.marker([pt[1], pt[0]], { icon, zIndexOffset: 200, interactive: !inEditMode.value })
    const note = stripPointFromNote(e.note)
    m.bindPopup(
      `<b>${esc(label)}</b> <span class="wm-pop-sub">${esc(formatTime(e.time_start))}</span>${
        note ? `<br/>${esc(note)}` : ''
      }`,
    )
    eventLayer.addLayer(m)
  }
}

/**
 * 绘制草稿层（最顶层）：顶点圆点 + 虚线预览 + territory ≥3 点时半透明填充。
 * 手画即所得——预览色与最终落图色一致（疆域紫 / 路径蓝）。
 */
function renderDraw() {
  if (!map || !drawLayer) return
  drawLayer.clearLayers()
  rubberLine = null
  const pts = draftPoints.value
  if (!props.drawMode || pts.length === 0) return
  const color = drawColor.value
  const latlngs = pts.map(({ p: [x, y] }) => [y, x] as [number, number])
  // 填充垫最底（territory 闭合预览）
  if (props.drawMode === 'territory' && pts.length >= 3) {
    drawLayer.addLayer(
      L.polygon(latlngs, { stroke: false, fillColor: color, fillOpacity: 0.13, interactive: false }),
    )
  }
  // 虚线预览
  if (pts.length >= 2) {
    drawLayer.addLayer(
      L.polyline(latlngs, { color, weight: 2, dashArray: '6 6', opacity: 0.9, interactive: false }),
    )
  }
  // 顶点圆点（首点略大，提示闭合起点）
  pts.forEach(({ p }, i) => {
    drawLayer!.addLayer(
      L.circleMarker([p[1], p[0]], {
        radius: i === 0 ? 5.5 : 4,
        color: '#fff',
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
        interactive: false,
      }),
    )
  })
}

/** 闭合绘制：territory 需 ≥3 顶点，move-path ≥0；不达标静默忽略（继续画） */
function finishDraw() {
  if (!props.drawMode) return
  const need = props.drawMode === 'territory' ? 3 : 0
  if (draftPoints.value.length < need) return
  const pts = draftPoints.value.map(({ p }) => [p[0], p[1]] as [number, number])
  clearDraft()
  emit('draw-complete', pts)
}

/** 删上一个顶点（Backspace） */
function undoVertex() {
  if (!props.drawMode || draftPoints.value.length === 0) return
  draftPoints.value.pop()
  renderDraw()
}

function clearDraft() {
  draftPoints.value = []
  renderDraw()
}

/** 占位面板图标（无底图时显示；有图片/笔迹后自动隐藏） */
function makePlaceholderIcon(): L.DivIcon {
  return L.divIcon({
    className: 'wm-placeholder-icon',
    html: `<div class="wm-placeholder">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" width="34" height="34"><path d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z"/></svg>
      <div class="wm-placeholder-title">世界地图占位</div>
      <div class="wm-placeholder-sub">点右上角「图片 / 画笔」绘制你自己的底图</div>
    </div>`,
    iconSize: [0, 0],
  })
}

function zoomIn() {
  map?.zoomIn()
}
function zoomOut() {
  map?.zoomOut()
}

onMounted(() => {
  if (!containerRef.value) return
  map = L.map(containerRef.value, {
    crs: L.CRS.Simple,
    minZoom: -2,
    maxZoom: 3,
    zoomSnap: 0.25,
    zoomControl: false, // 自绘缩放按钮（右上工具条）
    attributionControl: false,
    doubleClickZoom: false, // 双击留给「绘制闭合」；缩放已有自绘 +/- 按钮
  })
  baseImageLayer = L.layerGroup().addTo(map) // 底图图片（最底）
  trackLayer = L.layerGroup().addTo(map)
  territoryLayer = L.layerGroup().addTo(map)
  rippleLayer = L.layerGroup().addTo(map)
  eventLayer = L.layerGroup().addTo(map)
  markerLayer = L.layerGroup().addTo(map)
  characterLayer = L.layerGroup().addTo(map)
  drawLayer = L.layerGroup().addTo(map)
  editHitLayer = L.layerGroup().addTo(map)
  editSelLayer = L.layerGroup().addTo(map) // 底图编辑框最顶
  map.fitBounds(BOUNDS)
  map.on('click', (e: L.LeafletMouseEvent) => {
    if (props.drawMode) {
      // 绘制优先：点击收集顶点（[lng,lat] → 内部 [x,y]，带时间戳供双击识别）
      draftPoints.value.push({ p: [e.latlng.lng, e.latlng.lat], t: Date.now() })
      renderDraw()
      return
    }
    if (mapEditMode.value === 'images') {
      selectedLayerId.value = null // 点空白取消选中（图上的点击已被 stopPropagation）
      return
    }
    if (props.pickingMode === 'location') {
      emit('pick', [e.latlng.lng, e.latlng.lat])
    }
  })
  map.on('dblclick', (e: L.LeafletMouseEvent) => {
    if (!props.drawMode) return
    // 双击闭合。双击会伴随 1~2 次 click（数量随事件源不定，真实浏览器为 2）——
    // 把「与双击同位置且 600ms 内」的尾部合成顶点剥掉再闭合；
    // 用户真实顶点时间更早或位置不同，不会被误删。
    const now = Date.now()
    let removed = 0
    while (removed < 2) {
      const last = draftPoints.value[draftPoints.value.length - 1]
      if (!last) break
      const sameSpot =
        Math.abs(last.p[0] - e.latlng.lng) < 0.01 && Math.abs(last.p[1] - e.latlng.lat) < 0.01
      if (now - last.t < 600 && sameSpot) {
        draftPoints.value.pop()
        removed++
      } else break
    }
    finishDraw()
  })
  map.on('mousemove', (e: L.LeafletMouseEvent) => {
    if (!props.drawMode || draftPoints.value.length === 0 || !drawLayer) return
    const last = draftPoints.value[draftPoints.value.length - 1]
    const ll: [number, number][] = [
      [last.p[1], last.p[0]],
      [e.latlng.lat, e.latlng.lng],
    ]
    if (!rubberLine) {
      rubberLine = L.polyline(ll, {
        color: drawColor.value,
        weight: 1.5,
        dashArray: '4 6',
        opacity: 0.55,
        interactive: false,
      })
      drawLayer.addLayer(rubberLine)
    } else {
      rubberLine.setLatLngs(ll)
    }
  })
  // 缩放结束：按 zoom 阈值重渲带名字标签的层（缩小藏名字，放大显示）
  map.on('zoomend', () => {
    renderMarkers()
    renderCharacterMarkers()
    scheduleStrokeRedraw()
  })
  // 笔迹 canvas 与地图视图同步（拖动/缩放/窗口变化 → rAF 重绘）
  map.on('move zoom viewreset resize', scheduleStrokeRedraw)
  // 地点 popup 的就地改名/删除（popup DOM 随开随建，委托绑定无泄漏）
  map.on('popupopen', (e: L.PopupEvent) => {
    const root = e.popup.getElement()
    const box = root?.querySelector('.wm-pop-edit') as HTMLElement | null
    if (!box) return
    const locId = box.dataset.locId || ''
    const input = box.querySelector('[data-loc-name]') as HTMLInputElement | null
    const doSave = () => {
      const n = (input?.value || '').trim()
      if (n) {
        renameLocation(props.bookId, locId, n)
        showToast('地点已改名', 'success')
      }
      map?.closePopup()
    }
    box.querySelector('[data-act="save"]')?.addEventListener('click', doSave)
    input?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.stopPropagation()
        doSave()
      }
    })
    box.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
      const loc = locations.value.find((l) => l.id === locId)
      map?.closePopup()
      const ok = await showConfirm({
        title: '删除地点',
        message: `确定删除地点「${loc?.name || ''}」吗？`,
        warning: '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
        confirmText: '删除',
      })
      if (ok) {
        await deleteLocation(props.bookId, locId)
        showToast('地点已删除', 'success')
      }
    })
  })
  renderBaseImages()
  renderEditImages()
  renderMarkers()
  renderTracks()
  renderCharacterMarkers()
  renderTerritory()
  renderEventMarkers()
})

watch(locations, renderMarkers, { deep: true })
watch([worldState, currentTime, events], () => {
  spawnRipples(currentTime.value)
  renderTracks()
  renderCharacterMarkers()
  renderTerritory()
  renderEventMarkers()
}, { deep: true })
watch(layerVisible, () => {
  renderMarkers()
  renderTracks()
  renderCharacterMarkers()
  renderTerritory()
  renderEventMarkers()
}, { deep: true })
// 进入/退出沉浸编辑（疆域绘制 / 底图编辑）：清草稿 + 重渲各层（数据层禁交互）
watch(inEditMode, () => {
  clearDraft()
  renderMarkers()
  renderTracks()
  renderCharacterMarkers()
  renderTerritory()
  renderEventMarkers()
})
// 底图数据变化：重渲图片层 + 编辑框（拖动落库后触发，位置已就位仅刷新引用）
watch(mapLayers, () => {
  renderBaseImages()
  renderEditImages()
}, { deep: true })
watch(mapEditMode, () => renderEditImages())
watch(selectedLayerId, () => renderSelection())
watch(mapStrokes, scheduleStrokeRedraw, { deep: true })
watch(draftStroke, scheduleStrokeRedraw, { deep: true })
// 进入/退出画笔：清草稿重绘
watch(drawingMap, () => {
  painting = false
  draftStroke.value = []
  scheduleStrokeRedraw()
})

/** 聚焦到内部坐标 (x, y)——外部（事件/地点列表点击）调用 */
function focusAt(x: number, y: number, title?: string) {
  if (!map) return
  map.setView([y, x], Math.max(map.getZoom(), 1), { animate: true })
  if (title) {
    L.popup({ closeButton: true })
      .setLatLng([y, x])
      .setContent(`<b>${esc(title)}</b>`)
      .openOn(map)
  }
}
defineExpose({ focusAt, finishDraw, undoVertex, importImageAtView })

onBeforeUnmount(() => {
  if (strokeRafId !== null) cancelAnimationFrame(strokeRafId)
  map?.remove()
  map = null
  baseImageLayer = null
  trackLayer = null
  territoryLayer = null
  rippleLayer = null
  eventLayer = null
  markerLayer = null
  characterLayer = null
  drawLayer = null
  editHitLayer = null
  editSelLayer = null
  placeholderMarker = null
  rubberLine = null
})
</script>

<template>
  <div class="world-map-wrap">
    <div ref="containerRef" class="world-map" :class="{ drawing: drawMode }"></div>

    <!-- 墨迹滤镜 defs：疆域 SVG 位移毛边（古卷水彩晕染） -->
    <svg class="wm-svg-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <filter id="wm-ink" x="-8%" y="-8%" width="116%" height="116%">
          <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="4.5" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </defs>
    </svg>

    <!-- 烛光暗角（羊皮古卷氛围；不拦截交互） -->
    <div class="wm-vignette"></div>

    <!-- 手绘笔迹层（pointer-events 仅画笔态开启，其余穿透到地图） -->
    <canvas
      ref="strokeCanvasRef"
      class="wm-stroke-canvas"
      :class="{ drawing: mapEditMode === 'draw' }"
      @pointerdown="onStrokeDown"
      @pointermove="onStrokeMove"
      @pointerup="onStrokeUp"
      @pointercancel="onStrokeUp"
    ></canvas>

    <!-- 右上工具条：底图编辑入口 + 缩放 + 图层显隐 -->
    <div class="wm-toolbar">
      <button
        class="wm-tool"
        :class="{ on: mapEditMode === 'images' }"
        title="底图 · 导入图片拼贴"
        @click="toggleEdit('images')"
      >
        <Icon name="map" :size="14" />
      </button>
      <button
        class="wm-tool"
        :class="{ on: mapEditMode === 'draw' }"
        title="底图 · 手绘"
        @click="toggleEdit('draw')"
      >
        <Icon name="paint-brush" :size="14" />
      </button>
      <span class="wm-tool-sep"></span>
      <button class="wm-tool" title="放大" @click="zoomIn">
        <Icon name="plus" :size="14" />
      </button>
      <button class="wm-tool" title="缩小" @click="zoomOut">
        <Icon name="minus" :size="14" />
      </button>
      <span class="wm-tool-sep"></span>
      <button
        v-for="tg in LAYER_TOGGLES"
        :key="tg.key"
        class="wm-tool"
        :class="{ on: layerVisible[tg.key] }"
        :title="`${tg.label}图层`"
        @click="layerVisible[tg.key] = !layerVisible[tg.key]"
      >
        <Icon :name="tg.icon" :size="14" />
      </button>
    </div>

    <!-- 底图编辑面板（编辑态，左上浮动） -->
    <div v-if="mapEditMode" class="wm-editbar">
      <template v-if="mapEditMode === 'images'">
        <button class="wm-ebtn wm-ebtn--primary" @click="fileInputRef?.click()">
          <Icon name="arrow-up-tray" :size="13" />
          导入图片
        </button>
        <template v-if="selectedLayer">
          <span class="wm-esep"></span>
          <button
            class="wm-ebtn"
            title="置于顶层"
            @click="reorderLayer(bookId, selectedLayer.id, 'front')"
          >
            <Icon name="chevron-up" :size="13" />
            置顶
          </button>
          <button
            class="wm-ebtn"
            title="置于底层"
            @click="reorderLayer(bookId, selectedLayer.id, 'back')"
          >
            <Icon name="chevron-down" :size="13" />
            置底
          </button>
          <button class="wm-ebtn wm-ebtn--danger" title="删除图片（Del）" @click="removeSelected">
            <Icon name="trash" :size="13" />
          </button>
        </template>
        <span class="wm-ehint">点击图片选中 · 拖中心移动 · 拖角缩放 · 也可直接拖文件进地图</span>
      </template>
      <template v-else-if="mapEditMode === 'draw'">
        <div class="wm-palette">
          <button
            v-for="c in PEN_COLORS"
            :key="c"
            class="wm-swatch"
            :class="{ active: penColor === c && !eraserMode }"
            :style="{ background: c }"
            :title="`画笔 ${c}`"
            @click="penColor = c; eraserMode = false"
          ></button>
        </div>
        <span class="wm-esep"></span>
        <div class="wm-sizes">
          <button
            v-for="s in PEN_SIZES"
            :key="s"
            class="wm-size"
            :class="{ active: penWidth === s && !eraserMode }"
            :title="`粗细 ${s}`"
            @click="penWidth = s; eraserMode = false"
          >
            <span :style="{ width: s + 4 + 'px', height: s + 4 + 'px' }"></span>
          </button>
        </div>
        <span class="wm-esep"></span>
        <button
          class="wm-ebtn"
          :class="{ 'wm-ebtn--active': eraserMode }"
          title="橡皮（划过删除命中的笔迹）"
          @click="eraserMode = !eraserMode"
        >
          <Icon name="no-symbol" :size="13" />
          橡皮
        </button>
        <button
          class="wm-ebtn"
          :disabled="!canEditUndo"
          title="撤销（Ctrl+Z）"
          @click="editUndo()"
        >
          <Icon name="arrow-uturn-left" :size="13" />
        </button>
        <button
          class="wm-ebtn"
          :disabled="!canEditRedo"
          title="重做（Ctrl+Y）"
          @click="editRedo()"
        >
          <Icon name="arrow-uturn-right" :size="13" />
        </button>
        <button class="wm-ebtn wm-ebtn--danger" title="清空全部笔迹" @click="clearAllStrokes(bookId)">
          <Icon name="trash" :size="13" />
        </button>
        <span class="wm-ehint">拖动即绘制 · Esc 完成</span>
      </template>
      <button class="wm-ebtn wm-ebtn--done" title="退出编辑（Esc）" @click="exitMapEdit">
        完成
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.gif"
        hidden
        @change="onFile"
      />
    </div>
  </div>
</template>

<style scoped>
.world-map-wrap {
  position: relative;
  width: 100%;
  height: 100%;
}
/* 羊皮古卷画布：做旧纸底 + 纤维纹 + 淡墨绘制网格（零图片，纯 CSS gradient 不触 CSP） */
.world-map {
  width: 100%;
  height: 100%;
  min-height: 400px;
  background-color: #e7d7b6;
  background-image:
    /* 淡墨经纬细线（古地图绘制网格） */
    linear-gradient(rgba(107, 90, 68, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(107, 90, 68, 0.07) 1px, transparent 1px),
    /* 纸面纤维（两组低角度细纹交错） */
    repeating-linear-gradient(93deg, rgba(122, 92, 50, 0.03) 0 2px, transparent 2px 5px),
    repeating-linear-gradient(3deg, rgba(122, 92, 50, 0.022) 0 2px, transparent 2px 6px),
    /* 中心受光、边缘沉色的做旧渐层 */
    radial-gradient(ellipse at 46% 42%, rgba(255, 249, 231, 0.5), rgba(216, 195, 156, 0.35) 62%, rgba(196, 172, 130, 0.42) 100%),
    linear-gradient(160deg, #ecdfc3 0%, #e5d4b0 55%, #dcc8a0 100%);
  background-size:
    96px 96px,
    96px 96px,
    auto,
    auto,
    auto,
    auto;
  /* 独立层叠上下文：Leaflet 内部 pane z-index 高达 700，
     不隔离会压过页面 z-110 的模态/确认弹窗 */
  isolation: isolate;
}
:deep(.leaflet-container) {
  background: transparent;
  font: inherit;
}
/* 烛光暗角：压过数据层但不拦交互（阴影 pane 500 / marker 600 / tooltip 650 之上取 645） */
.wm-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 645;
  background:
    radial-gradient(ellipse at 50% 46%, transparent 52%, rgba(74, 56, 30, 0.12) 78%, rgba(60, 44, 22, 0.3) 100%);
  mix-blend-mode: multiply;
}
.wm-svg-defs {
  position: absolute;
  width: 0;
  height: 0;
  pointer-events: none;
}
/* 绘制期十字光标（压过 Leaflet 的 grab 手型） */
.world-map.drawing :deep(.leaflet-container) {
  cursor: crosshair !important;
}
.wm-toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 500;
  padding: 4px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 4px 14px rgba(60, 48, 30, 0.12);
}
.wm-tool {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}
.wm-tool:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.wm-tool.on {
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
}
.wm-tool-sep {
  height: 1px;
  margin: 1px 3px;
  background: var(--border-color);
}
/* ===== 底图编辑面板（左上浮动） ===== */
.wm-editbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 4px 14px rgba(60, 48, 30, 0.14);
  max-width: calc(100% - 90px);
  flex-wrap: wrap;
}
.wm-ebtn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.13s;
  white-space: nowrap;
}
.wm-ebtn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.wm-ebtn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.wm-ebtn--primary:hover {
  background: var(--accent-600);
  color: #fff;
}
.wm-ebtn--danger:hover {
  border-color: #dc2626;
  color: #dc2626;
}
.wm-ebtn--done {
  font-weight: 600;
}
.wm-esep {
  width: 1px;
  height: 16px;
  background: var(--border-color);
  margin: 0 2px;
}
.wm-ehint {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
/* 画笔态笔迹 canvas */
.wm-stroke-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 460;
}
.wm-stroke-canvas.drawing {
  pointer-events: auto;
  cursor: crosshair;
}
/* 画笔工具 */
.wm-palette {
  display: flex;
  gap: 4px;
}
.wm-swatch {
  width: 18px;
  height: 18px;
  border-radius: 9999px;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px var(--border-color);
  cursor: pointer;
  transition: box-shadow 0.12s;
}
.wm-swatch.active {
  box-shadow: 0 0 0 2px var(--accent-500);
}
.wm-sizes {
  display: flex;
  gap: 4px;
}
.wm-size {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
}
.wm-size span {
  border-radius: 9999px;
  background: var(--text-secondary);
}
.wm-size.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
}
.wm-ebtn--active {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
  font-weight: 600;
}
</style>

<style>
/* ===== 全局（Leaflet divIcon 的 DOM 在 Vue scoped 之外）===== */

/* 地点 marker：空心环点 + 名字标签 */
.wm-loc-icon {
  background: transparent;
  border: none;
}
.wm-loc {
  display: flex;
  align-items: center;
  gap: 5px;
  transform: translate(-8px, -8px);
}
.wm-loc-ring {
  width: 13px;
  height: 13px;
  border-radius: 9999px;
  background: rgba(249, 242, 226, 0.92);
  border: 3px solid var(--c, #7c6aad);
  box-shadow: 0 1px 5px rgba(60, 44, 22, 0.3);
  transition: transform 0.15s ease-out;
}
.wm-loc:hover .wm-loc-ring {
  transform: scale(1.25);
}
.wm-loc-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  padding: 1px 6px;
  border-radius: 6px;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(60, 48, 30, 0.14);
}

/* 人物 marker：实心圆点 + 名字；存活呼吸烛光、在途青墨脉冲、核心角色星芒 */
.wm-char-icon {
  background: transparent;
  border: none;
}
.wm-char {
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translate(-8px, -8px);
}
.wm-char-head {
  width: 15px;
  height: 15px;
  border-radius: 9999px;
  background: var(--c, #f59e0b);
  border: 2.5px solid #f4ead4;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
  animation: wm-breathe 3.2s ease-in-out infinite;
}
@keyframes wm-breathe {
  50% {
    box-shadow:
      0 1px 6px rgba(0, 0, 0, 0.4),
      0 0 10px 2px rgba(255, 214, 140, 0.4);
  }
}
.wm-char-name {
  margin-top: 2px;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-primary, #2c2c2c);
  background: rgba(249, 242, 226, 0.92);
  border: 1px solid rgba(107, 90, 68, 0.35);
  padding: 0 5px;
  border-radius: 5px;
  white-space: nowrap;
}
.wm-char--moving .wm-char-head {
  background: #3f6f8f;
  animation: wm-pulse 1.2s ease-in-out infinite;
}
/* 核心角色（importance≥7）：金环星芒 */
.wm-char--star .wm-char-head {
  border-color: #c9a227;
}
.wm-char--star .wm-char-head::after {
  content: '';
  position: absolute;
  width: 15px;
  height: 15px;
  border-radius: 9999px;
  border: 1.5px dashed rgba(201, 162, 39, 0.85);
  animation: wm-star-spin 14s linear infinite;
}
.wm-char-head {
  position: relative;
}
@keyframes wm-star-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes wm-pulse {
  50% {
    box-shadow: 0 0 0 7px rgba(63, 111, 143, 0.28);
  }
}

/* 疆域：墨迹晕染（SVG 位移滤镜给边界毛边，纸面水彩感） */
path.wm-territory {
  filter: url(#wm-ink);
}

/* 轨迹：在途虚线流动（行军） */
path.wm-track-flow {
  animation: wm-dash-flow 1.15s linear infinite;
}
@keyframes wm-dash-flow {
  to {
    stroke-dashoffset: -64;
  }
}

/* 事件涟漪：游标扫过时刻绽放（一次性动画，1.5s 后由 JS 移除） */
.wm-ripple-icon {
  background: transparent;
  border: none;
}
.wm-ripple {
  position: absolute;
  width: 8px;
  height: 8px;
  margin: -4px 0 0 -4px;
  border-radius: 9999px;
  border: 2px solid var(--c, #94a3b8);
  animation: wm-ripple 1.4s ease-out forwards;
}
.wm-ripple::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 9999px;
  border: 1.5px solid var(--c, #94a3b8);
  animation: wm-ripple 1.4s 0.22s ease-out forwards;
}
.wm-ripple--big,
.wm-ripple--big::after {
  border-width: 3px;
}
@keyframes wm-ripple {
  from {
    transform: scale(0.4);
    opacity: 0.95;
  }
  to {
    transform: scale(7);
    opacity: 0;
  }
}

/* 事件 marker：圆形印章（印泥做旧 + 手按不规则边） */
.wm-evt-icon {
  background: transparent;
  border: none;
}
.wm-evt {
  display: block;
  width: 11px;
  height: 11px;
  transform: translate(-5.5px, -5.5px) rotate(8deg);
  background: transparent;
  border: 2.5px solid var(--c, #94a3b8);
  border-radius: 46% 54% 52% 48% / 52% 46% 54% 48%;
  box-shadow:
    inset 0 0 0 1.5px rgba(244, 234, 212, 0.55),
    0 1px 3px rgba(60, 44, 22, 0.35);
  cursor: pointer;
  transition: transform 0.15s ease-out;
}
.wm-evt:hover {
  transform: translate(-5.5px, -5.5px) rotate(8deg) scale(1.35);
}

/* 底图编辑手柄（中心十字 / 角方块） */
.wm-handle-icon {
  background: transparent;
  border: none;
}
.wm-handle {
  width: 12px;
  height: 12px;
  transform: translate(-6px, -6px);
  background: #fff;
  border: 2px solid #7c6aad;
  border-radius: 3px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  cursor: move;
}
.wm-handle--center {
  border-radius: 9999px;
  background: #7c6aad;
}

/* popup 次要文字 */
.wm-pop-sub {
  color: var(--text-muted, #a89e90);
  font-size: 11px;
}
.wm-pop-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 2px;
  color: var(--text-primary, #2c2c2c);
}
.wm-pop-intro {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-secondary, #64748b);
  max-width: 200px;
}
/* 地点 popup 就地改名/删除 */
.wm-pop-edit {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.wm-pop-input {
  width: 110px;
  padding: 3px 7px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 6px;
  background: var(--bg-canvas, #fff);
  color: var(--text-primary, #2c2c2c);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.wm-pop-input:focus {
  border-color: var(--accent-500, #7c6aad);
}
.wm-pop-btn {
  padding: 3px 8px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #64748b);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.wm-pop-btn:hover {
  border-color: var(--accent-500, #7c6aad);
  color: var(--accent-500, #7c6aad);
}
.wm-pop-btn--danger:hover {
  border-color: #dc2626;
  color: #dc2626;
}

/* 占位面板（零图片方案） */
.wm-placeholder-icon {
  background: transparent;
  border: none;
}
.wm-placeholder {
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 420px;
  padding: 44px 32px;
  border: 2.5px dashed rgba(107, 90, 68, 0.4);
  border-radius: 20px;
  background: rgba(249, 242, 226, 0.4);
  box-shadow: inset 0 0 32px rgba(122, 92, 50, 0.08);
  color: rgba(109, 90, 60, 0.8);
  text-align: center;
  pointer-events: none;
}
.wm-placeholder-title {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted, #a89e90);
}
.wm-placeholder-sub {
  font-size: 12px;
  color: var(--text-muted, #a89e90);
  opacity: 0.8;
}
</style>
